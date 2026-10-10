from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.accounts import rbac
from apps.audit import services as audit
from apps.boxes.models import Box, QrCode
from apps.inventory import availability
from apps.inventory.models import InventoryAsset, InventoryProduct, TrackingMode
from apps.makerspaces import limits
from apps.makerspaces.models import Makerspace
from apps.operations.models import QrPrintBatch, QrPrintBatchItem


def _target_label(qr):
    if qr.target_type == QrCode.TargetType.BOX:
        return Box.objects.get(pk=qr.target_id).label
    if qr.target_type == QrCode.TargetType.ASSET:
        asset = InventoryAsset.objects.select_related("product").get(pk=qr.target_id)
        return f"{asset.product.name} - {asset.asset_tag}"
    return InventoryProduct.objects.get(pk=qr.target_id).name


@transaction.atomic
def add_qr_to_batch(batch, qr, label_text="", sort_order=None):
    # Serialize additions and relabels against the first send/print transition.
    batch = QrPrintBatch.objects.select_for_update().get(pk=batch.pk)
    if batch.status != QrPrintBatch.Status.DRAFT:
        raise ValidationError("Only draft QR print batches can be modified.")
    if qr.makerspace_id != batch.makerspace_id:
        raise ValidationError("QR code belongs to a different makerspace.")
    resolved_label = label_text or _target_label(qr)
    explicit_sort_order = sort_order is not None
    if sort_order is None:
        sort_order = batch.items.count()
    item, created = QrPrintBatchItem.objects.get_or_create(
        batch=batch,
        qr_code=qr,
        defaults={
            "label_text": resolved_label,
            "target_type": qr.target_type,
            "target_id": qr.target_id,
            "sort_order": sort_order,
        },
    )
    if not created:
        update_fields = ["label_text", "target_type", "target_id"]
        item.label_text = resolved_label
        item.target_type = qr.target_type
        item.target_id = qr.target_id
        if explicit_sort_order:
            item.sort_order = sort_order
            update_fields.append("sort_order")
        item.save(update_fields=update_fields)
    return item


def _create_asset_qr(actor, asset):
    qr, _ = QrCode.objects.get_or_create(
        makerspace=asset.makerspace,
        target_type=QrCode.TargetType.ASSET,
        target_id=asset.id,
        status=QrCode.Status.ACTIVE,
        defaults={"created_by": actor},
    )
    return qr


def _assets_missing_active_qr(product, limit):
    asset_ids_with_qr = QrCode.objects.filter(
        makerspace=product.makerspace,
        target_type=QrCode.TargetType.ASSET,
        target_id__in=product.assets.values("id"),
        status=QrCode.Status.ACTIVE,
    ).values("target_id")
    return list(
        product.assets.select_for_update()
        .exclude(id__in=asset_ids_with_qr)
        .order_by("created_at", "id")[:limit]
    )


def generate_assets_with_qr(actor, product, data):
    created = []
    with transaction.atomic():
        # Quota checks also lock the tenant. Take that lock before product/batch
        # so generation and first-send cannot acquire these rows in reverse order.
        spaces = rbac.scope_by_action(actor, rbac.Action.MANAGE_QR, Makerspace.objects.all(), field="id")
        get_object_or_404(spaces.select_for_update(), pk=product.makerspace_id)
        product = InventoryProduct.objects.select_for_update().get(pk=product.pk)
        if product.tracking_mode != TrackingMode.INDIVIDUAL:
            product.tracking_mode = TrackingMode.INDIVIDUAL
            product.save(update_fields=["tracking_mode", "updated_at"])

        batch = None
        if data.get("print_batch_id"):
            batch = QrPrintBatch.objects.get(pk=data["print_batch_id"], makerspace=product.makerspace)
        elif data.get("create_print_batch"):
            batch = QrPrintBatch.objects.create(
                makerspace=product.makerspace,
                title=f"{product.name} unit QR labels",
                created_by=actor,
            )
        serials = data.get("serial_numbers") or []
        name_prefix = data.get("name_prefix") or product.name
        existing_count = product.assets.count()
        missing_qr_assets = _assets_missing_active_qr(product, data["count"])

        for asset in missing_qr_assets:
            qr = _create_asset_qr(actor, asset)
            if batch:
                add_qr_to_batch(batch, qr, label_text=f"{name_prefix} {asset.asset_tag}")
            created.append({"asset": asset, "qr": qr})

        remaining_count = data["count"] - len(missing_qr_assets)
        limits.check_quota(product.makerspace, "assets", adding=remaining_count)
        for idx in range(remaining_count):
            next_number = existing_count + idx + 1
            asset_tag = f"{product.slug if hasattr(product, 'slug') else product.id}-{next_number:04d}"
            asset = InventoryAsset.objects.create(
                makerspace=product.makerspace,
                product=product,
                box=product.box,
                asset_tag=asset_tag,
                serial_number=serials[idx] if idx < len(serials) else "",
                notes=f"{name_prefix} #{next_number}",
            )
            qr = _create_asset_qr(actor, asset)
            if batch:
                add_qr_to_batch(batch, qr, label_text=f"{name_prefix} {next_number}")
            created.append({"asset": asset, "qr": qr})

        availability.reconcile_individual_product_from_assets(product)
        audit.record(actor, "asset_units.generated", makerspace=product.makerspace, target=product, meta={"count": data["count"]})
    return created, batch


def mark_batch_printed(actor, batch):
    with transaction.atomic():
        locked = QrPrintBatch.objects.select_for_update().get(pk=batch.pk)
        # Only a draft batch can be marked printed: block re-printing and prevent an
        # archived batch from being silently unarchived back to printed.
        if locked.status != QrPrintBatch.Status.DRAFT:
            raise ValidationError(
                f"Only draft QR print batches can be marked printed (status: {locked.status})."
            )
        locked.status = QrPrintBatch.Status.PRINTED
        locked.printed_at = timezone.now()
        locked.save(update_fields=["status", "printed_at"])
        audit.record(actor, "qr_print_batch.printed", makerspace=locked.makerspace, target=locked)
        return locked

