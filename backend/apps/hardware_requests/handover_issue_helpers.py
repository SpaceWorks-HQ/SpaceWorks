from apps.audit import services as audit
from apps.boxes.models import QrCode, QrScanEvent
from apps.hardware_requests.models import HardwareRequestItemAsset
from apps.hardware_requests.workflow_errors import InvalidTransition, RequestValidationError
from apps.inventory.models import InventoryAsset, TrackingMode


INDIVIDUAL_HANDOUT_ERROR = (
    "Individual-tracked products require scanned asset QR codes for handout."
)


def validate_broken_rejects(locked, rejects_by_item):
    """Per-item broken-reject is quantity-mode only this pass: individual-tracked items
    flip specific asset rows at return, so rejecting an abstract count here would drift
    the asset statuses from the product buckets."""
    items = {item.id: item for item in locked.items.select_related("product")}
    for item_id, (broken, _disposition) in rejects_by_item.items():
        item = items.get(item_id)
        if item is None:
            raise RequestValidationError("Unknown item in broken rejects.")
        if broken > item.accepted_quantity:
            raise RequestValidationError(
                "Cannot reject more units as broken than were accepted."
            )
        if item.product.tracking_mode == TrackingMode.INDIVIDUAL:
            raise RequestValidationError(
                "Individual-tracked items can't be rejected as broken at handover; "
                "issue them and mark the specific unit damaged at return."
            )


def issue_individual_assets(actor, locked, asset_qr_payloads):
    individual_items = list(
        locked.items.select_related("product")
        .filter(product__tracking_mode=TrackingMode.INDIVIDUAL, accepted_quantity__gt=0)
        .order_by("product_id", "pk")
    )
    expected_count = sum(item.accepted_quantity for item in individual_items)
    if expected_count == 0:
        return
    if len(asset_qr_payloads) != expected_count:
        raise RequestValidationError(INDIVIDUAL_HANDOUT_ERROR)

    seen_qr_ids = set()
    qrs_by_payload = {
        qr.payload: qr
        for qr in QrCode.objects.select_for_update()
        .filter(
            makerspace=locked.makerspace,
            payload__in=asset_qr_payloads,
            target_type=QrCode.TargetType.ASSET,
        )
        .order_by("pk")
    }
    qrs = []
    for payload in asset_qr_payloads:
        qr = qrs_by_payload.get(payload)
        if qr is None:
            raise RequestValidationError(INDIVIDUAL_HANDOUT_ERROR)
        if qr.status != QrCode.Status.ACTIVE:
            raise RequestValidationError("QR code is not active for this makerspace.")
        if qr.id in seen_qr_ids:
            raise InvalidTransition("The same QR code was scanned more than once.")
        seen_qr_ids.add(qr.id)
        qrs.append(qr)

    assets_by_id = {
        asset.pk: asset
        for asset in InventoryAsset.objects.select_for_update()
        .filter(
            pk__in=[qr.target_id for qr in qrs],
            makerspace=locked.makerspace,
            status=InventoryAsset.Status.AVAILABLE,
        )
        .order_by("pk")
    }
    assets_by_product = {}
    qr_by_asset_id = {}
    for qr in qrs:
        asset = assets_by_id.get(qr.target_id)
        if asset is None:
            raise RequestValidationError(INDIVIDUAL_HANDOUT_ERROR)
        assets_by_product.setdefault(asset.product_id, []).append(asset)
        qr_by_asset_id[asset.pk] = qr

    for item in individual_items:
        assets = assets_by_product.get(item.product_id, [])
        if len(assets) < item.accepted_quantity:
            raise RequestValidationError(INDIVIDUAL_HANDOUT_ERROR)
        item_assets = sorted(assets[: item.accepted_quantity], key=lambda asset: asset.pk)
        del assets[: item.accepted_quantity]
        for asset in item_assets:
            asset.status = InventoryAsset.Status.ISSUED
            asset.save(update_fields=["status", "updated_at"])
            HardwareRequestItemAsset.objects.create(
                request_item=item,
                asset=asset,
                outcome=HardwareRequestItemAsset.Outcome.ISSUED,
            )
            qr = qr_by_asset_id[asset.pk]
            QrScanEvent.objects.create(
                makerspace=locked.makerspace,
                qr_code=qr,
                request=locked,
                actor=actor,
                context=QrScanEvent.Context.ISSUE,
            )
            audit.record(
                actor,
                "asset.issued",
                makerspace=locked.makerspace,
                target=asset,
                meta={
                    "request_id": locked.pk,
                    "request_item_id": item.pk,
                    "qr_id": qr.pk,
                },
            )

    if any(assets for assets in assets_by_product.values()):
        raise RequestValidationError(INDIVIDUAL_HANDOUT_ERROR)
