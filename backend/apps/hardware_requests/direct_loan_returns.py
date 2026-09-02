from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.audit import services as audit
from apps.boxes.models import QrCode, QrScanEvent
from apps.evidence import storage
from apps.evidence.finalization import charge_storage_once, lock_evidence_for_attachment
from apps.evidence.models import EvidencePhoto
from apps.hardware_requests.direct_loan_audit import record_item_logs
from apps.hardware_requests.models import PublicToolLoan, ReturnEvent
from apps.hardware_requests.return_helpers import (
    OUTCOME_MAP,
    build_resolutions,
    finalize_return_status,
    remaining_quantity,
    write_accountability,
)
from apps.hardware_requests.workflow_errors import (
    EvidenceNotUploaded,
    InvalidTransition,
    RequestValidationError,
    ReturnValidationError,
)
from apps.inventory import availability
from apps.inventory.models import InventoryAsset, TrackingMode


def return_direct_loan(
    loan,
    actor,
    evidence_id,
    notes,
    resolutions,
    *,
    qr_payload="",
):
    notes = str(notes or "").strip()
    if not notes:
        raise RequestValidationError("Return notes are required.")
    evidence = EvidencePhoto.objects.filter(
        pk=evidence_id,
        makerspace_id=loan.makerspace_id,
        evidence_type=EvidencePhoto.EvidenceType.RETURN,
    ).first()
    if evidence is None:
        raise RequestValidationError("Invalid return evidence.")
    if loan.status != PublicToolLoan.Status.CHECKED_OUT:
        raise InvalidTransition("Direct loan is not currently checked out.")

    finalized = validate_evidence_upload(evidence, label="Return")

    with transaction.atomic():
        locked = (
            PublicToolLoan.objects.select_for_update(of=("self",))
            .select_related("container", "makerspace", "request")
            .get(pk=loan.pk)
        )
        if locked.status != PublicToolLoan.Status.CHECKED_OUT:
            raise InvalidTransition("Direct loan is not currently checked out.")
        if not lock_evidence_for_attachment(evidence.pk):
            raise ReturnValidationError("Evidence has expired under the retention policy.")
        if (
            PublicToolLoan.objects.filter(return_evidence=evidence).exists()
            or ReturnEvent.objects.filter(evidence=evidence).exists()
        ):
            raise ReturnValidationError("Evidence already used.")
        charge_storage_once(evidence, finalized.size)
        return_qr = _return_scan_qr(locked, qr_payload)
        outstanding = [
            item
            for item in locked.request.items.select_related("product").all()
            if remaining_quantity(item) > 0
        ]
        if outstanding:
            validated = build_resolutions(locked.request, resolutions)
            _require_full_resolution(locked.request, validated)
            availability.return_items(locked.request, validated)
            for resolution in validated:
                item = resolution["item"]
                if item.product.tracking_mode == TrackingMode.INDIVIDUAL:
                    _flip_direct_loan_assets(actor, locked, item, resolution)
            write_accountability(actor, locked.request, evidence, validated)
        elif resolutions:
            # Nothing outstanding (e.g. a container-only handout) but the caller
            # sent resolutions — reject rather than silently ignore them.
            raise ReturnValidationError("This direct loan has no outstanding units to resolve.")
        event = _create_return_event(actor, locked, evidence, notes)
        finalize_return_status(locked.request, actor)

        locked.status = PublicToolLoan.Status.RETURNED
        locked.returned_at = timezone.now()
        locked.return_evidence = evidence
        locked.return_notes = notes
        try:
            with transaction.atomic():
                locked.save(
                    update_fields=[
                        "status",
                        "returned_at",
                        "return_evidence",
                        "return_notes",
                    ]
                )
        except IntegrityError as exc:
            raise ReturnValidationError("Evidence already used.") from exc
        if return_qr is not None:
            QrScanEvent.objects.create(
                makerspace=locked.makerspace,
                qr_code=return_qr,
                actor=actor,
                context=QrScanEvent.Context.RETURN,
                request=locked.request,
            )
        record_item_logs(
            actor, "admin_direct.returned", locked.makerspace, locked.request, locked
        )
        audit.record(
            actor,
            "evidence.attached",
            makerspace=locked.makerspace,
            target=evidence,
            meta={"request_id": locked.request_id, "return_event_id": event.pk},
        )
        return locked


def _require_full_resolution(request, validated):
    resolved_by_item = {
        resolution["item"].pk: (
            resolution["returned"] + resolution["damaged"] + resolution["missing"]
        )
        for resolution in validated
    }
    for item in request.items.select_related("product").all():
        remaining = remaining_quantity(item)
        if remaining <= 0:
            continue
        if resolved_by_item.get(item.pk) != remaining:
            raise ReturnValidationError(
                "Direct loan returns must resolve every outstanding unit."
            )


def _flip_direct_loan_assets(actor, locked, item, resolution):
    asset_ids = [int(asset_id) for asset_id in (locked.asset_ids or [])]
    assets = list(
        InventoryAsset.objects.select_for_update()
        .filter(
            pk__in=asset_ids,
            product=item.product,
            makerspace=locked.makerspace,
            status=InventoryAsset.Status.ISSUED,
        )
        .order_by("pk")
    )
    assets_by_id = {asset.pk: asset for asset in assets}
    asset_outcomes = resolution["asset_outcomes"]
    if asset_outcomes:
        requested_ids = [asset["asset_id"] for asset in asset_outcomes]
        if len(set(requested_ids)) != len(requested_ids) or any(
            asset_id not in assets_by_id for asset_id in requested_ids
        ):
            raise ReturnValidationError(
                "Return asset does not belong to this direct loan."
            )
        for asset_outcome in asset_outcomes:
            asset = assets_by_id[asset_outcome["asset_id"]]
            asset.status = OUTCOME_MAP[asset_outcome["outcome"]][1]
            asset.save(update_fields=["status", "updated_at"])
        return

    quantity = resolution["returned"]
    if quantity <= 0:
        return
    if len(assets) < quantity:
        raise ReturnValidationError("Return quantity exceeds issued direct loan assets.")
    for asset in assets[:quantity]:
        asset.status = InventoryAsset.Status.AVAILABLE
        asset.save(update_fields=["status", "updated_at"])


def _create_return_event(actor, locked, evidence, notes):
    try:
        with transaction.atomic():
            return ReturnEvent.objects.create(
                request=locked.request,
                makerspace=locked.makerspace,
                box=locked.container,
                evidence=evidence,
                remark=notes,
                actor=actor,
            )
    except IntegrityError as exc:
        raise ReturnValidationError("Evidence already used.") from exc


def _return_scan_qr(loan, qr_payload):
    expected_ids = [int(qr_id) for qr_id in (loan.qr_ids or [])]
    qr_payload = str(qr_payload or "").strip()
    if not expected_ids and loan.container_id:
        container_qr = (
            QrCode.objects.select_for_update()
            .filter(
                makerspace=loan.makerspace,
                target_type=QrCode.TargetType.BOX,
                target_id=loan.container_id,
                status=QrCode.Status.ACTIVE,
            )
            .first()
        )
        if container_qr is not None:
            expected_ids = [container_qr.id]

    if expected_ids:
        if not qr_payload:
            raise RequestValidationError("Return QR scan is required.")
        qr = (
            QrCode.objects.select_for_update()
            .filter(pk__in=expected_ids, makerspace=loan.makerspace, payload=qr_payload)
            .first()
        )
        if qr is None:
            raise RequestValidationError("Scanned QR does not match this direct loan.")
        return qr

    if not qr_payload:
        return None
    qr = (
        QrCode.objects.select_for_update()
        .filter(
            makerspace=loan.makerspace,
            payload=qr_payload,
            status=QrCode.Status.ACTIVE,
        )
        .first()
    )
    if qr is None:
        raise RequestValidationError("QR code is not active for this makerspace.")
    return qr


def validate_evidence_upload(evidence, *, label):
    try:
        result = storage.finalize_upload(evidence, settings.EVIDENCE_MAX_BYTES)
    except storage.EvidenceObjectValidationError as exc:
        if exc.code == "missing":
            raise EvidenceNotUploaded(f"{label} evidence has not been uploaded.") from exc
        raise ReturnValidationError(
            f"{label} evidence is invalid or exceeds the size limit."
        ) from exc
    if result is None:
        raise EvidenceNotUploaded(f"{label} evidence has not been uploaded.")
    return result
