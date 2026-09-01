from django.db import connection
from django.db.models import Count

from apps.inventory.availability_types import InsufficientStock
from apps.inventory.models import InventoryAsset, InventoryProduct, TrackingMode


ASSET_QUANTITY_BUCKETS = {
    InventoryAsset.Status.AVAILABLE: "available_quantity",
    InventoryAsset.Status.RESERVED: "reserved_quantity",
    InventoryAsset.Status.ISSUED: "issued_quantity",
    InventoryAsset.Status.DAMAGED: "damaged_quantity",
    InventoryAsset.Status.LOST: "lost_quantity",
    InventoryAsset.Status.MAINTENANCE: "needs_fix_quantity",
}

ASSET_QUANTITY_FIELDS = tuple(dict.fromkeys(ASSET_QUANTITY_BUCKETS.values()))


def reconcile_individual_product_from_assets(product):
    """Make individual-tracked product buckets match serialized asset rows."""
    if product.tracking_mode != TrackingMode.INDIVIDUAL:
        return product

    counts = {field: 0 for field in ASSET_QUANTITY_FIELDS}
    for row in (
        InventoryAsset.objects.filter(product_id=product.pk)
        .values("status")
        .annotate(count=Count("id"))
    ):
        bucket = ASSET_QUANTITY_BUCKETS.get(row["status"])
        if bucket:
            counts[bucket] += row["count"]

    total = sum(counts.values())
    changed = []
    for field, value in counts.items():
        if getattr(product, field) != value:
            setattr(product, field, value)
            changed.append(field)
    if product.total_quantity != total:
        product.total_quantity = total
        changed.append("total_quantity")

    if changed:
        product.save(update_fields=[*changed, "updated_at"])
    return product


def move_asset_status(asset, new_status):
    """Move one serialized asset between product quantity buckets.

    The caller must already be inside transaction.atomic() and hold the asset row
    lock. This service locks the product row before changing bucket counts.
    """
    if not connection.in_atomic_block:
        raise RuntimeError("move_asset_status must be called inside transaction.atomic().")
    old_status = asset.status
    if old_status == new_status:
        return asset
    old_bucket = ASSET_QUANTITY_BUCKETS.get(old_status)
    new_bucket = ASSET_QUANTITY_BUCKETS.get(new_status)
    if old_bucket is None or new_bucket is None:
        raise InsufficientStock(
            "Asset status transition is not backed by inventory quantity buckets."
        )

    product = InventoryProduct.objects.select_for_update().get(pk=asset.product_id)
    reconcile_individual_product_from_assets(product)
    old_value = getattr(product, old_bucket)
    if old_value < 1:
        raise InsufficientStock(
            f"Product {product.pk} has no {old_bucket} stock to move."
        )
    setattr(product, old_bucket, old_value - 1)
    setattr(product, new_bucket, getattr(product, new_bucket) + 1)
    product.save(update_fields=[old_bucket, new_bucket, "updated_at"])
    asset.status = new_status
    asset.save(update_fields=["status", "updated_at"])
    return asset
