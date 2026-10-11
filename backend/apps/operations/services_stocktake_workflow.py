from django.db import IntegrityError, transaction
from django.core.exceptions import ObjectDoesNotExist
from apps.accounts import rbac
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.audit import services as audit
from apps.inventory.models import InventoryAsset, InventoryProduct
from apps.notifications.emit import emit_notification
from apps.operations.models import (
    StocktakeLine,
    StocktakeSession,
)
from apps.boxes.models import Box
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


from .stocktake_discipline import session_policy, needs_approval


def _count_target(model, actor, pk, makerspace, action=rbac.Action.EDIT_INVENTORY):
    rows = rbac.scope_by_action(actor, action, model.objects.all())
    try:
        return rows.get(pk=pk, makerspace=makerspace)
    except ObjectDoesNotExist as exc:
        raise ValidationError("Select a count target in this makerspace.") from exc


def _container(actor, pk, makerspace):
    return _count_target(Box, actor, pk, makerspace) if pk else None


def _locked_stocktake(actor, stocktake):
    return rbac.scope_by_action(actor, rbac.Action.EDIT_INVENTORY,
                               StocktakeSession.objects.select_for_update()).get(pk=stocktake.pk)


@transaction.atomic
def create_stocktake(actor, makerspace, data):
    try:
        container = _container(actor, data.get("container_id"), makerspace)
    except ObjectDoesNotExist as exc:
        raise ValidationError({"container_id": "Select a container in this makerspace."}) from exc
    stocktake = StocktakeSession.objects.create(
        makerspace=makerspace,
        container=container,
        started_by=actor,
        notes=data.get("notes", ""),
        **session_policy(makerspace, data, actor=actor),
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
        box = _count_target(Box, actor, qr.target_id, stocktake.makerspace, rbac.Action.VIEW_INVENTORY)
        return {"type": "box", "container_id": box.id, "label": box.label, "code": box.code}
    if qr.target_type == QrCode.TargetType.ASSET:
        asset = _count_target(InventoryAsset, actor, qr.target_id, stocktake.makerspace, rbac.Action.VIEW_INVENTORY)
        return {
            "type": "asset",
            "asset_id": asset.id,
            "product_id": asset.product_id,
            "asset_tag": asset.asset_tag,
            "product": asset.product.name,
            **({} if stocktake.blind else {"status": asset.status}),
        }
    product = _count_target(InventoryProduct, actor, qr.target_id, stocktake.makerspace, rbac.Action.VIEW_INVENTORY)
    return {"type": "product", "product_id": product.id, "name": product.name}


def add_stocktake_line(actor, stocktake, data):
    with transaction.atomic():
        locked = _locked_stocktake(actor, stocktake)
        if locked.status not in {StocktakeSession.Status.DRAFT, StocktakeSession.Status.COUNTING}:
            raise ValidationError("Cannot add count lines after stocktake is completed.")
        product = None
        asset = None
        expected = 0
        condition = data.get("condition") or StocktakeLine.Condition.AVAILABLE
        try:
            container = _container(actor, data.get("container_id"), locked.makerspace)
        except ObjectDoesNotExist as exc:
            raise ValidationError({"container_id": "Select a container in this makerspace."}) from exc
        _validate_line_container(locked, container)
        if data.get("asset_id"):
            asset = _count_target(InventoryAsset, actor, data["asset_id"], locked.makerspace)
            _validate_asset_count(asset, data["counted_quantity"])
            _validate_item_container(locked, container, asset=asset)
            expected = 1 if _asset_bucket(asset.status) == condition else 0
        else:
            product = _count_target(InventoryProduct, actor, data["product_id"], locked.makerspace)
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
        locked = _locked_stocktake(actor, stocktake)
        if locked.status != StocktakeSession.Status.COUNTING:
            raise ValidationError("Only counting stocktakes can be completed.")
        if locked.variance_threshold is not None and not locked.lines.exists():
            raise ValidationError("Count at least one line before completing a disciplined stocktake.")
        locked.approval_required = needs_approval(locked)
        locked.status = StocktakeSession.Status.COMPLETED if locked.approval_required else StocktakeSession.Status.APPROVED
        locked.completed_at = timezone.now()
        locked.save(update_fields=["status", "completed_at", "approval_required"])
        audit.record(actor, "stocktake.completed", makerspace=locked.makerspace, target=locked)
        emit_notification(
            locked.makerspace,
            level="info",
            event="stocktake.completed",
            title="Stocktake awaiting approval" if locked.approval_required else "Stocktake ready to apply",
            body=f"Stocktake #{locked.pk} was completed. " + (
                "Review is required." if locked.approval_required else "Variances are within the configured threshold."),
        )
        return locked


def approve_stocktake(actor, stocktake):
    with transaction.atomic():
        locked = _locked_stocktake(actor, stocktake)
        if locked.status != StocktakeSession.Status.COMPLETED:
            raise ValidationError("Only completed stocktakes can be approved.")
        if locked.variance_threshold is not None and not rbac.can(actor, rbac.Action.MANAGE_MAKERSPACE, locked.makerspace_id):
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied()
        from apps.audit.models import AuditLog
        counted = rbac.scope_by_action(actor, rbac.Action.EDIT_INVENTORY, AuditLog.objects.all()).filter(
            makerspace=locked.makerspace, actor=actor, action="stocktake.line_counted",
            target_type=locked._meta.label_lower, target_id=str(locked.pk)).exists()
        if locked.variance_threshold is not None and (locked.started_by_id == actor.pk or counted):
            raise ValidationError("A different approver must review a variance above the threshold.")
        locked.status = StocktakeSession.Status.APPROVED
        locked.approved_by = actor
        locked.approved_at = timezone.now()
        locked.save(update_fields=["status", "approved_by", "approved_at"])
        audit.record(actor, "stocktake.approved", makerspace=locked.makerspace, target=locked)
        return locked


def apply_stocktake_adjustments(actor, stocktake):
    with transaction.atomic():
        locked = _locked_stocktake(actor, stocktake)
        if locked.status != StocktakeSession.Status.APPROVED:
            raise ValidationError("Only approved stocktakes can be applied.")
        if locked.approval_required and locked.variance_threshold is not None and not rbac.can(actor, rbac.Action.MANAGE_MAKERSPACE, locked.makerspace_id):
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied()
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
