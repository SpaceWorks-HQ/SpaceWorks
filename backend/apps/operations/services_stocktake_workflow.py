from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.audit import services as audit
from apps.inventory.models import InventoryAsset, InventoryProduct
from apps.notifications.emit import emit_notification
from apps.operations.models import (
    StocktakeLine,
    StocktakeSession,
)
from apps.operations.services_shared import _container
from apps.operations.services_stocktake_helpers import (
    _apply_ledger_entries,
    _asset_bucket,
    _ledger_entries_for_line,
    _product_expected,
    _record_adjustment,
    _reject_duplicate_line,
    _validate_asset_count,
    _validate_item_container,
    _validate_line_container,
    _validate_line_fresh,
    _validate_line_scope,
)


def create_stocktake(actor, makerspace, data):
    container = _container(data.get("container_id"), makerspace.id)
    stocktake = StocktakeSession.objects.create(
        makerspace=makerspace,
        container=container,
        started_by=actor,
        notes=data.get("notes", ""),
    )
    audit.record(actor, "stocktake.created", makerspace=makerspace, target=stocktake)
    return stocktake


def resolve_scan_target(actor, stocktake, payload):
    from apps.accounts import rbac
    from apps.boxes.access import qr_for_action
    from apps.boxes.models import Box, QrCode

    qr = qr_for_action(actor, rbac.Action.VIEW_INVENTORY, payload=payload, status=QrCode.Status.ACTIVE)
    if qr.makerspace_id != stocktake.makerspace_id:
        raise ValidationError("QR belongs to a different makerspace.")
    if qr.target_type == QrCode.TargetType.BOX:
        box = Box.objects.get(pk=qr.target_id)
        return {"type": "box", "container_id": box.id, "label": box.label, "code": box.code}
    if qr.target_type == QrCode.TargetType.ASSET:
        asset = InventoryAsset.objects.select_related("product").get(pk=qr.target_id)
        return {
            "type": "asset",
            "asset_id": asset.id,
            "product_id": asset.product_id,
            "asset_tag": asset.asset_tag,
            "product": asset.product.name,
            "status": asset.status,
        }
    product = InventoryProduct.objects.get(pk=qr.target_id)
    return {"type": "product", "product_id": product.id, "name": product.name}


def add_stocktake_line(actor, stocktake, data):
    with transaction.atomic():
        locked = StocktakeSession.objects.select_for_update().get(pk=stocktake.pk)
        if locked.status not in {StocktakeSession.Status.DRAFT, StocktakeSession.Status.COUNTING}:
            raise ValidationError("Cannot add count lines after stocktake is completed.")
        product = None
        asset = None
        expected = 0
        condition = data.get("condition") or StocktakeLine.Condition.AVAILABLE
        container = _container(data.get("container_id"), locked.makerspace_id)
        _validate_line_container(locked, container)
        if data.get("asset_id"):
            asset = InventoryAsset.objects.get(pk=data["asset_id"], makerspace=locked.makerspace)
            _validate_asset_count(asset, data["counted_quantity"])
            _validate_item_container(locked, container, asset=asset)
            expected = 1 if _asset_bucket(asset.status) == condition else 0
        else:
            product = InventoryProduct.objects.get(pk=data["product_id"], makerspace=locked.makerspace)
            _validate_item_container(locked, container, product=product)
            expected = _product_expected(product, condition)
        _reject_duplicate_line(locked, product, asset, condition, container)
        counted = data["counted_quantity"]
        try:
            line = StocktakeLine.objects.create(
                stocktake=locked,
                product=product,
                asset=asset,
                container=container,
                expected_quantity=expected,
                counted_quantity=counted,
                variance_quantity=counted - expected,
                condition=condition,
                notes=data.get("notes", ""),
            )
        except IntegrityError as exc:
            raise ValidationError("Duplicate stocktake line.") from exc
        audit.record(actor, "stocktake.line_counted", makerspace=locked.makerspace, target=locked, meta={"line_id": line.id})
        return line


def complete_stocktake(actor, stocktake):
    with transaction.atomic():
        locked = StocktakeSession.objects.select_for_update().get(pk=stocktake.pk)
        if locked.status != StocktakeSession.Status.COUNTING:
            raise ValidationError("Only counting stocktakes can be completed.")
        locked.status = StocktakeSession.Status.COMPLETED
        locked.completed_at = timezone.now()
        locked.save(update_fields=["status", "completed_at"])
        audit.record(actor, "stocktake.completed", makerspace=locked.makerspace, target=locked)
        emit_notification(
            locked.makerspace,
            level="info",
            event="stocktake.completed",
            title="Stocktake awaiting approval",
            body=f"Stocktake #{locked.pk} was completed and is awaiting approval.",
        )
        return locked


def approve_stocktake(actor, stocktake):
    with transaction.atomic():
        locked = StocktakeSession.objects.select_for_update().get(pk=stocktake.pk)
        if locked.status != StocktakeSession.Status.COMPLETED:
            raise ValidationError("Only completed stocktakes can be approved.")
        locked.status = StocktakeSession.Status.APPROVED
        locked.approved_by = actor
        locked.approved_at = timezone.now()
        locked.save(update_fields=["status", "approved_by", "approved_at"])
        audit.record(actor, "stocktake.approved", makerspace=locked.makerspace, target=locked)
        return locked


def apply_stocktake_adjustments(actor, stocktake):
    with transaction.atomic():
        locked = StocktakeSession.objects.select_for_update().get(pk=stocktake.pk)
        if locked.status != StocktakeSession.Status.APPROVED:
            raise ValidationError("Only approved stocktakes can be applied.")
        for line in locked.lines.select_related("product", "asset", "container"):
            _validate_line_scope(locked, line)
            _validate_line_fresh(line)
            entries = _ledger_entries_for_line(actor, locked, line)
            _apply_ledger_entries(entries)
            _record_adjustment(actor, locked, line, entries)
        locked.status = StocktakeSession.Status.APPLIED
        locked.save(update_fields=["status"])
        audit.record(actor, "stocktake.adjustments_applied", makerspace=locked.makerspace, target=locked)
        return locked
