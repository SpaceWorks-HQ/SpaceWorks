"""Self-checkout issue workflow and active-QR guard."""

from datetime import timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.audit import services as audit
from apps.boxes.models import QrScanEvent
from apps.evidence.finalization import charge_storage_once
from apps.evidence.models import EvidencePhoto
from apps.hardware_requests.direct_loan_returns import validate_evidence_upload
from apps.hardware_requests.models import PublicToolLoan
from apps.hardware_requests.self_checkout_evidence import _lock_unused_evidence, _public_evidence
from apps.hardware_requests.self_checkout_helpers import _checkout_target, _issued_request, _locked_qr
from apps.hardware_requests.workflow_errors import InvalidTransition, RequestValidationError
from apps.makerspaces.guards import require_feature, require_feature_locked
from apps.makerspaces.models import Makerspace
from apps.makerspaces.servability import is_servable


def checkout_tool(makerspace, requester, payload, *, evidence_id, remark=""):
    # Gate on the feature and on servability BEFORE touching evidence. Promotion moved
    # out of the transaction so its row locks never span S3 I/O, and moving the evidence
    # work up with it put it ahead of the feature check -- so a makerspace with
    # self-checkout disabled reported an evidence error instead of the feature error, and
    # promoted an upload on the way there. The locked recheck below is still the
    # authority; this is the cheap pre-check that keeps the ordering honest.
    # By pk, not by the instance the caller handed us: require_feature() trusts a
    # Makerspace argument as-is, so a stale in-memory copy would pass a gate the stored
    # row has already closed.
    current = require_feature(makerspace.pk, "inventory.self_checkout")
    if not is_servable(current):
        raise RequestValidationError("Makerspace is not available.")
    evidence = _public_evidence(
        makerspace, requester, evidence_id, EvidencePhoto.EvidenceType.ISSUE
    )
    finalized = validate_evidence_upload(evidence, label="Issue")
    with transaction.atomic():
        makerspace = Makerspace.objects.select_for_update().get(pk=makerspace.pk)
        makerspace = require_feature_locked(makerspace, "inventory.self_checkout")
        if not is_servable(makerspace):
            raise RequestValidationError("Makerspace is not available.")
        due_at = timezone.now() + timedelta(days=(makerspace.default_loan_days or 7))
        _lock_unused_evidence(evidence, issue=True)
        charge_storage_once(evidence, finalized.size)
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


