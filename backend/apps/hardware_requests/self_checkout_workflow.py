from collections import Counter
from datetime import timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.audit import services as audit
from apps.boxes.models import Box, QrCode, QrScanEvent
from apps.evidence.models import EvidencePhoto
from apps.hardware_requests.models import (
    HardwareRequest,
    HardwareRequestItem,
    PublicProblemReport,
    PublicToolLoan,
    ReturnEvent,
)
from apps.hardware_requests.self_checkout_helpers import (
    _checkout_box,
    _checkout_target,
    _create_issued_request,
    _eligible_asset,
    _eligible_product,
    _issue_product,
    _issued_request,
    _locked_qr,
    _return_request_items,
)
from apps.hardware_requests.workflow_errors import (
    InvalidTransition,
    RequestValidationError,
    RequesterBlocked,
    ReturnValidationError,
)
from apps.hardware_requests.direct_loan_returns import validate_evidence_upload
from apps.inventory import availability
from apps.inventory.models import InventoryAsset, InventoryProduct
from apps.makerspaces.guards import require_feature_locked
from apps.makerspaces.models import Makerspace
from apps.makerspaces.servability import is_servable
from apps.notifications.emit import emit_notification


def checkout_tool(makerspace, requester, payload, *, evidence_id, remark=""):
    with transaction.atomic():
        makerspace = Makerspace.objects.select_for_update().get(pk=makerspace.pk)
        makerspace = require_feature_locked(makerspace, "inventory.self_checkout")
        if not is_servable(makerspace):
            raise RequestValidationError("Makerspace is not available.")
        due_at = timezone.now() + timedelta(days=(makerspace.default_loan_days or 7))
        evidence = _public_evidence(makerspace, requester, evidence_id, EvidencePhoto.EvidenceType.ISSUE)
        _lock_unused_evidence(evidence, issue=True)
        validate_evidence_upload(evidence, label="Issue")
        qr = _locked_qr(makerspace, payload)
        if qr_has_active_loan(makerspace, qr):
            raise InvalidTransition("This QR code is already checked out.")

        target_label, product_quantities, asset_ids, container = _checkout_target(qr)
        hardware_request = _issued_request(
            makerspace,
            requester,
            requester.username,
            product_quantities,
            requester_name=requester.display_name,
            contact_email=requester.email,
            contact_phone=requester.phone,
            return_due_at=due_at,
        )
        hardware_request.issue_evidence = evidence
        hardware_request.issue_remark = str(remark or "").strip()
        hardware_request.save(update_fields=["issue_evidence", "issue_remark", "updated_at"])
        loan = PublicToolLoan.objects.create(
            makerspace=makerspace,
            qr_code=qr,
            qr_ids=[qr.id],
            container=container,
            request=hardware_request,
            requester=requester,
            target_type=qr.target_type,
            target_id=qr.target_id,
            target_label=target_label,
            asset_ids=asset_ids,
            due_at=due_at,
        )
        QrScanEvent.objects.create(
            makerspace=makerspace,
            qr_code=qr,
            actor=requester,
            context=QrScanEvent.Context.ISSUE,
            request=hardware_request,
        )
        audit.record(
            requester,
            "public_tool.checked_out",
            makerspace=makerspace,
            target=hardware_request,
            meta={"qr_id": qr.id, "target": target_label},
        )
        return loan


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
    with transaction.atomic():
        makerspace = Makerspace.objects.select_for_update().get(pk=makerspace.pk)
        if not is_servable(makerspace):
            raise RequestValidationError("Makerspace is not available.")
        evidence = _public_evidence(makerspace, requester, evidence_id, EvidencePhoto.EvidenceType.RETURN)
        _lock_unused_evidence(evidence, issue=False)
        validate_evidence_upload(evidence, label="Return")
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
        loan.request.status = HardwareRequest.Status.RETURNED
        loan.request.closed_by = requester
        loan.request.closed_at = loan.returned_at
        loan.request.save(update_fields=["status", "closed_by", "closed_at", "updated_at"])
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


def _public_evidence(makerspace, requester, evidence_id, evidence_type):
    evidence = EvidencePhoto.objects.filter(
        pk=evidence_id,
        makerspace=makerspace,
        evidence_type=evidence_type,
        uploaded_by=requester,
    ).first()
    if evidence is None:
        raise RequestValidationError("Invalid evidence.")
    return evidence


def _lock_unused_evidence(evidence, *, issue):
    EvidencePhoto.objects.select_for_update().get(pk=evidence.pk)
    if issue:
        if HardwareRequest.objects.filter(issue_evidence=evidence).exists():
            raise RequestValidationError("Evidence already used.")
        return
    if (
        PublicToolLoan.objects.filter(return_evidence=evidence).exists()
        or ReturnEvent.objects.filter(evidence=evidence).exists()
    ):
        raise ReturnValidationError("Evidence already used.")


def qr_has_active_loan(makerspace, qr):
    """True if this QR is part of any currently checked-out loan.

    A direct handout can bundle several QRs onto one loan; only the first lands in
    the `qr_code` FK (the partial-unique constraint allows just one), so the rest
    are tracked in `qr_ids`. Checking both closes the re-issue gap where a
    secondary QR looked free. Callers hold the relevant QR row lock(s), so the
    check is race-free against concurrent checkouts of the same QR."""
    return (
        PublicToolLoan.objects.filter(
            makerspace=makerspace,
            status=PublicToolLoan.Status.CHECKED_OUT,
        )
        .filter(Q(qr_code=qr) | Q(qr_ids__contains=[qr.id]))
        .exists()
    )


__all__ = [
    "Box",
    "Counter",
    "HardwareRequest",
    "HardwareRequestItem",
    "InventoryAsset",
    "InventoryProduct",
    "InvalidTransition",
    "PublicToolLoan",
    "Q",
    "QrCode",
    "QrScanEvent",
    "RequestValidationError",
    "_checkout_box",
    "_checkout_target",
    "_create_issued_request",
    "_eligible_asset",
    "_eligible_product",
    "_issue_product",
    "_issued_request",
    "_locked_qr",
    "_return_request_items",
    "audit",
    "availability",
    "checkout_tool",
    "qr_has_active_loan",
    "return_tool",
    "timezone",
    "transaction",
]
