"""Evidence-backed member return workflow."""

from django.db import transaction
from django.utils import timezone

from apps.audit import services as audit
from apps.boxes.models import QrScanEvent
from apps.evidence.finalization import charge_storage_once
from apps.evidence.models import EvidencePhoto
from apps.hardware_requests.direct_loan_returns import validate_evidence_upload
from apps.hardware_requests.models import PublicProblemReport, PublicToolLoan
from apps.hardware_requests.return_helpers import finalize_return_status
from apps.hardware_requests.self_checkout_evidence import _lock_unused_evidence, _public_evidence
from apps.hardware_requests.self_checkout_helpers import _locked_qr, _return_request_items
from apps.hardware_requests.workflow_errors import InvalidTransition, RequestValidationError, RequesterBlocked
from apps.inventory.models import InventoryAsset
from apps.makerspaces.models import Makerspace
from apps.makerspaces.servability import is_servable
from apps.notifications.emit import emit_notification


def return_tool(
    makerspace,
    requester,
    payload,
    *,
    evidence_id,
    remark,
    report_problem=False,
    problem_note="",
):
    remark = str(remark or "").strip()
    if not remark:
        raise RequestValidationError("Return remark is required.")
    # Same ordering rule as checkout_tool: an unservable makerspace must not reach
    # evidence handling. Re-read for the same stale-instance reason; the locked recheck
    # inside the transaction remains the authority.
    if not is_servable(Makerspace.objects.get(pk=makerspace.pk)):
        raise RequestValidationError("Makerspace is not available.")
    evidence = _public_evidence(
        makerspace, requester, evidence_id, EvidencePhoto.EvidenceType.RETURN
    )
    finalized = validate_evidence_upload(evidence, label="Return")
    with transaction.atomic():
        makerspace = Makerspace.objects.select_for_update().get(pk=makerspace.pk)
        if not is_servable(makerspace):
            raise RequestValidationError("Makerspace is not available.")
        _lock_unused_evidence(evidence, issue=False)
        charge_storage_once(evidence, finalized.size)
        qr = _locked_qr(makerspace, payload)
        loan = (
            PublicToolLoan.objects.select_for_update()
            .select_related("request", "requester")
            .filter(qr_code=qr, status=PublicToolLoan.Status.CHECKED_OUT)
            .first()
        )
        if loan is None:
            raise InvalidTransition("This QR code is not currently checked out.")
        if loan.requester_id != requester.id:
            raise RequesterBlocked("This tool was checked out by a different user.")

        _return_request_items(loan.request)
        if loan.asset_ids:
            InventoryAsset.objects.select_for_update().filter(
                pk__in=loan.asset_ids,
                makerspace=makerspace,
            ).update(status=InventoryAsset.Status.AVAILABLE)

        loan.status = PublicToolLoan.Status.RETURNED
        loan.returned_at = timezone.now()
        loan.return_evidence = evidence
        loan.return_notes = remark
        loan.save(update_fields=["status", "returned_at", "return_evidence", "return_notes"])
        finalize_return_status(loan.request, requester)
        QrScanEvent.objects.create(
            makerspace=makerspace,
            qr_code=qr,
            actor=requester,
            context=QrScanEvent.Context.RETURN,
            request=loan.request,
        )
        audit.record(
            requester,
            "public_tool.returned",
            makerspace=makerspace,
            target=loan.request,
            meta={"qr_id": qr.id, "target": loan.target_label},
        )
        if report_problem:
            report = PublicProblemReport.objects.create(
                makerspace=makerspace,
                loan=loan,
                request=loan.request,
                requester=requester,
                note=problem_note.strip(),
            )
            audit.record(
                requester,
                "public_tool.problem_reported",
                makerspace=makerspace,
                target=report,
                meta={"loan_id": loan.pk, "request_id": loan.request_id},
            )
            emit_notification(
                makerspace,
                level="warning",
                event="problem_report.filed",
                title="Tool problem reported",
                body=f"Problem report #{report.pk} filed for loan #{loan.pk}.",
            )
        return loan


