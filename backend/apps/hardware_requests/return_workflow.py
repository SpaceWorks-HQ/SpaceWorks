from django.conf import settings
from django.db import IntegrityError, transaction

from apps.audit import services as audit
from apps.boxes.models import Box, BoxScan
from apps.evidence import storage
from apps.evidence.finalization import charge_storage_once, lock_evidence_for_attachment
from apps.evidence.models import EvidencePhoto
from apps.hardware_requests import notifications
from apps.hardware_requests.models import (
    HardwareRequest,
    PublicToolLoan,
    ReturnEvent,
)
from apps.hardware_requests.return_helpers import (
    build_resolutions,
    finalize_return_status,
    flip_individual_asset_returns,
    write_accountability,
)
from apps.hardware_requests.workflow_errors import (
    EvidenceNotUploaded,
    InvalidTransition,
    ReturnValidationError,
)
from apps.hardware_requests.workflow_utils import locked_request
from apps.inventory import availability


def return_items(actor, request, evidence_id, remark, box_code, resolutions):
    remark = str(remark or "").strip()
    if not remark:
        raise ReturnValidationError("Return remark is required.")

    evidence = _return_evidence(request, evidence_id)
    _require_returnable(request)
    try:
        finalized = storage.finalize_upload(evidence, settings.EVIDENCE_MAX_BYTES)
    except storage.EvidenceObjectValidationError as exc:
        if exc.code == "missing":
            raise EvidenceNotUploaded("Return evidence has not been uploaded.") from exc
        raise ReturnValidationError(
            "Return evidence is invalid or exceeds the size limit."
        ) from exc
    if finalized is None:
        raise EvidenceNotUploaded("Return evidence has not been uploaded.")

    with transaction.atomic():
        locked = locked_request(request)
        _require_returnable(locked)
        # Lock the evidence row + reject a photo already consumed by a direct-loan
        # return. ReturnEvent.evidence (OneToOne) already blocks reviewed-request
        # reuse; this shared row lock serializes against the direct-loan return
        # path, which has no DB constraint spanning the two tables.
        if not lock_evidence_for_attachment(evidence.pk):
            raise ReturnValidationError("Evidence has expired under the retention policy.")
        if PublicToolLoan.objects.filter(return_evidence=evidence).exists():
            raise ReturnValidationError("Return evidence has already been used.")
        charge_storage_once(evidence, finalized.size)
        box = _matching_box(locked, box_code)
        scan = _record_scan(actor, locked, box)
        validated_resolutions = build_resolutions(locked, resolutions)

        availability.return_items(locked, validated_resolutions)
        event = _create_event(actor, locked, box, evidence, remark)
        flip_individual_asset_returns(actor, locked, validated_resolutions, event)
        write_accountability(actor, locked, evidence, validated_resolutions)
        request_action = finalize_return_status(locked, actor)
        _audit_return(actor, locked, box, evidence, scan, request_action)
        notifications.notify_request_returned(locked)
        return locked


def _return_evidence(request, evidence_id):
    evidence = EvidencePhoto.objects.filter(
        pk=evidence_id,
        makerspace_id=request.makerspace_id,
        evidence_type=EvidencePhoto.EvidenceType.RETURN,
    ).first()
    if evidence is None:
        raise ReturnValidationError("Invalid return evidence.")
    return evidence


def _require_returnable(locked):
    if locked.status not in {
        HardwareRequest.Status.ISSUED,
        HardwareRequest.Status.PARTIALLY_RETURNED,
    }:
        raise InvalidTransition(
            f"Cannot return hardware request with status {locked.status}."
        )


def _matching_box(locked, box_code):
    box = Box.objects.filter(makerspace=locked.makerspace, code=box_code).first()
    if box is None or box.pk != locked.assigned_box_id:
        raise ReturnValidationError("Scanned box does not match this loan.")
    return box


def _record_scan(actor, locked, box):
    return BoxScan.objects.create(
        makerspace=locked.makerspace,
        box=box,
        request=locked,
        actor=actor,
        context=BoxScan.Context.RETURN,
    )

def _create_event(actor, locked, box, evidence, remark):
    try:
        return ReturnEvent.objects.create(
            request=locked,
            makerspace=locked.makerspace,
            box=box,
            evidence=evidence,
            remark=remark,
            actor=actor,
        )
    except IntegrityError as exc:
        raise ReturnValidationError("Evidence already used.") from exc


def _audit_return(actor, locked, box, evidence, scan, request_action):
    audit.record(
        actor,
        request_action,
        makerspace=locked.makerspace,
        target=locked,
        meta={"box_id": box.pk, "evidence_id": evidence.pk},
    )
    audit.record(
        actor,
        "evidence.attached",
        makerspace=locked.makerspace,
        target=evidence,
        meta={"request_id": locked.pk},
    )
    audit.record(
        actor,
        "box.scanned",
        makerspace=locked.makerspace,
        target=scan,
        meta={"box_id": box.pk, "request_id": locked.pk},
    )
