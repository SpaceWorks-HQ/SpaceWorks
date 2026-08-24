from django.db import connection, transaction
from django.db.models import Count

from apps.inventory.models import InventoryAsset, InventoryProduct, TrackingMode
from apps.inventory.availability_types import InsufficientStock


def adjust_quantities(
    product, *, delta_available, delta_damaged, delta_lost, reason, actor
):
    """Apply signed deltas to a product's available/damaged/lost buckets, recompute
    total, record an InventoryAdjustment, and audit. Row-locked; refuses to make any
    bucket negative (raises InsufficientStock)."""
    with transaction.atomic():
        locked = InventoryProduct.objects.select_for_update().get(pk=product.pk)
        available = locked.available_quantity + delta_available
        damaged = locked.damaged_quantity + delta_damaged
        lost = locked.lost_quantity + delta_lost
        if available < 0 or damaged < 0 or lost < 0:
            raise InsufficientStock(
                "Quantity adjustment cannot make a bucket negative."
            )

        locked.available_quantity = available
        locked.damaged_quantity = damaged
        locked.lost_quantity = lost
        locked.total_quantity = (
            locked.available_quantity
            + locked.reserved_quantity
            + locked.issued_quantity
            + locked.damaged_quantity
            + locked.lost_quantity
            + locked.needs_fix_quantity
        )
        locked.save(
            update_fields=[
                "available_quantity",
                "damaged_quantity",
                "lost_quantity",
                "total_quantity",
                "updated_at",
            ]
        )

        from apps.audit import services as audit
        from apps.operations.models import InventoryAdjustment

        InventoryAdjustment.objects.create(
            makerspace=locked.makerspace,
            product=locked,
            delta_available=delta_available,
            delta_damaged=delta_damaged,
            delta_lost=delta_lost,
            reason=reason,
            created_by=actor,
        )
        audit.record(
            actor,
            "inventory.quantity_adjusted",
            makerspace=locked.makerspace,
            target=locked,
            meta={
                "delta_available": delta_available,
                "delta_damaged": delta_damaged,
                "delta_lost": delta_lost,
                "reason": reason,
            },
        )
    return locked


def consume_available(product, quantity, reason, actor):
    """Consume whole units from available inventory through the adjustment ledger."""
    if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0:
        raise InsufficientStock("Consumption quantity must be a positive integer.")
    return adjust_quantities(
        product,
        delta_available=-quantity,
        delta_damaged=0,
        delta_lost=0,
        reason=reason,
        actor=actor,
    )


def move_available_to_triage_bucket(product, quantity, *, outcome, reason, actor):
    """Move returned public-report stock out of available after staff triage.

    Public self-checkout returns place stock back into AVAILABLE before a public
    problem report is reviewed. Triage is a later correction from available into
    the staff-confirmed unavailable bucket.
    """
    quantity = int(quantity)
    if quantity <= 0:
        raise InsufficientStock("Triage quantity must be positive.")
    if outcome == "damaged":
        return adjust_quantities(
            product,
            delta_available=-quantity,
            delta_damaged=quantity,
            delta_lost=0,
            reason=reason,
            actor=actor,
        )
    if outcome == "missing":
        return adjust_quantities(
            product,
            delta_available=-quantity,
            delta_damaged=0,
            delta_lost=quantity,
            reason=reason,
            actor=actor,
        )
    if outcome != "needs_fix":
        raise InsufficientStock("Unsupported triage inventory outcome.")

    if not connection.in_atomic_block:
        raise RuntimeError(
            "move_available_to_triage_bucket must be called inside transaction.atomic()."
        )
    locked = InventoryProduct.objects.select_for_update().get(pk=product.pk)
    if locked.available_quantity < quantity:
        raise InsufficientStock(
            f"Cannot move {quantity}: only {locked.available_quantity} available."
        )
    locked.available_quantity -= quantity
    locked.needs_fix_quantity += quantity
    locked.total_quantity = (
        locked.available_quantity
        + locked.reserved_quantity
        + locked.issued_quantity
        + locked.damaged_quantity
        + locked.lost_quantity
        + locked.needs_fix_quantity
    )
    locked.save(
        update_fields=[
            "available_quantity",
            "needs_fix_quantity",
            "total_quantity",
            "updated_at",
        ]
    )

    from apps.audit import services as audit
    from apps.operations.models import InventoryAdjustment

    InventoryAdjustment.objects.create(
        makerspace=locked.makerspace,
        product=locked,
        delta_available=-quantity,
        delta_damaged=0,
        delta_lost=0,
        reason=reason,
        created_by=actor,
    )
    audit.record(
        actor,
        "inventory.quantity_adjusted",
        makerspace=locked.makerspace,
        target=locked,
        meta={
            "delta_available": -quantity,
            "delta_damaged": 0,
            "delta_lost": 0,
            "target_bucket": "needs_fix",
            "reason": reason,
        },
    )
    return locked

def issue_available(product, quantity):
    """Move `quantity` of a single product straight from available -> issued.

    The no-reservation flows (public self-checkout, admin direct handout) never go
    through accept/reserve, so they skip the reserved bucket. The caller must
    already hold a row lock on `product` (select_for_update) inside an atomic
    block; centralizing the math here keeps the never-below-zero invariant in one
    place instead of being open-coded in each workflow."""
    if not connection.in_atomic_block:
        raise RuntimeError("issue_available must be called inside transaction.atomic().")
    if product.available_quantity < quantity:
        raise InsufficientStock(
            f"Insufficient stock for product {product.pk}: "
            f"requested {quantity}, available {product.available_quantity}."
        )
    product.available_quantity -= quantity
    product.issued_quantity += quantity
    product.save(update_fields=["available_quantity", "issued_quantity", "updated_at"])


def return_to_available(product, quantity):
    """Move `quantity` of a single product back from issued -> available.

    Mirror of `issue_available` for the no-reservation return paths. Same locking
    contract as above."""
    if not connection.in_atomic_block:
        raise RuntimeError("return_to_available must be called inside transaction.atomic().")
    if product.issued_quantity < quantity:
        raise InsufficientStock(
            f"Insufficient issued stock for product {product.pk}: "
            f"returning {quantity}, issued {product.issued_quantity}."
        )
    product.issued_quantity -= quantity
    product.available_quantity += quantity
    product.save(update_fields=["issued_quantity", "available_quantity", "updated_at"])


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
    source.save(update_fields=["available_quantity", "total_quantity", "updated_at"])
    destination.save(
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
    product.save(
        update_fields=[
            "available_quantity",
            "damaged_quantity",
            "lost_quantity",
            "total_quantity",
            "updated_at",
        ]
    )

