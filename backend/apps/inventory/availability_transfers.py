from apps.inventory.availability_stock import save_stock_change
from django.db import connection
from apps.inventory.models import InventoryProduct
from apps.inventory.availability_types import InsufficientStock


def transfer_available_quantity(source_product, destination_product, quantity):
    """Move available quantity from one product row to another.

    Stock-transfer workflows use this for quantity-tracked moves where the
    destination may be another container or another makerspace. Keeping the
    available/total bucket math here preserves the inventory availability
    invariant that no bucket can go below zero.
    """
    if not connection.in_atomic_block:
        raise RuntimeError(
            "transfer_available_quantity must be called inside transaction.atomic()."
        )
    quantity = int(quantity)
    if quantity <= 0:
        raise InsufficientStock("Transfer quantity must be positive.")
    if source_product.pk == destination_product.pk:
        return source_product, destination_product

    ids = sorted([source_product.pk, destination_product.pk])
    locked = {
        product.pk: product
        for product in InventoryProduct.objects.select_for_update()
        .filter(pk__in=ids)
        .order_by("pk")
    }
    source = locked[source_product.pk]
    destination = locked[destination_product.pk]
    if source.available_quantity < quantity or source.total_quantity < quantity:
        raise InsufficientStock(
            f"Insufficient stock for product {source.pk}: "
            f"requested {quantity}, available {source.available_quantity}."
        )

    source.available_quantity -= quantity
    source.total_quantity -= quantity
    destination.available_quantity += quantity
    destination.total_quantity += quantity
    save_stock_change(source, update_fields=["available_quantity", "total_quantity", "updated_at"])
    save_stock_change(destination,
        update_fields=["available_quantity", "total_quantity", "updated_at"]
    )
    return source, destination


def apply_stocktake_delta(product, *, delta_available=0, delta_damaged=0, delta_lost=0):
    """Apply signed deltas to available/damaged/lost for a stocktake variance,
    recompute total_quantity as the sum of all buckets, and save. Caller must
    hold the product row lock inside transaction.atomic(). Refuses to make
    available/damaged/lost negative (raises InsufficientStock)."""
    if not connection.in_atomic_block:
        raise RuntimeError(
            "apply_stocktake_delta must be called inside transaction.atomic()."
        )
    product.available_quantity += delta_available
    product.damaged_quantity += delta_damaged
    product.lost_quantity += delta_lost
    if min(product.available_quantity, product.damaged_quantity, product.lost_quantity) < 0:
        raise InsufficientStock("Stocktake adjustment would make inventory negative.")
    product.total_quantity = (
        product.available_quantity
        + product.reserved_quantity
        + product.issued_quantity
        + product.damaged_quantity
        + product.lost_quantity
        + product.needs_fix_quantity
    )
    save_stock_change(product,
        update_fields=[
            "available_quantity",
            "damaged_quantity",
            "lost_quantity",
            "total_quantity",
            "updated_at",
        ]
    )

