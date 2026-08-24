from django.db import connection

from apps.inventory.availability_types import InsufficientStock
from apps.inventory.models import InventoryAsset, InventoryProduct, TrackingMode


def reserve_for_request(request):
    if not connection.in_atomic_block:
        raise RuntimeError("reserve_for_request must be called inside transaction.atomic().")

    items = list(request.items.order_by("product_id"))
    product_ids = [item.product_id for item in items]
    products = {
        product.pk: product
        for product in InventoryProduct.objects.select_for_update()
        .filter(pk__in=product_ids)
        .order_by("pk")
    }

    # Aggregate accepted quantity per product (a product may span multiple items).
    required_by_product = {}
    for item in items:
        if item.accepted_quantity > 0:
            required_by_product[item.product_id] = (
                required_by_product.get(item.product_id, 0) + item.accepted_quantity
            )

    for product_id in sorted(required_by_product):
        quantity = required_by_product[product_id]
        product = products[product_id]

        # Individual-asset guard runs UNDER the same row lock as the reservation
        # update, reading the freshly-locked reserved_quantity as the committed
        # baseline. A concurrent accept for the same product blocks on this lock
        # until we commit, then re-reads the incremented baseline and is rejected -
        # closing the check-then-reserve race a standalone pre-check would leave open.
        assert_individual_assets_available(product, quantity)

        if product.available_quantity < quantity:
            raise InsufficientStock(
                f"Insufficient stock for product {product.pk}: "
                f"requested {quantity}, available {product.available_quantity}."
            )

        product.available_quantity -= quantity
        product.reserved_quantity += quantity
        product.save(
            update_fields=[
                "available_quantity",
                "reserved_quantity",
                "updated_at",
            ]
        )


def assert_individual_assets_available(product, required_qty):
    """Fail fast when quantity buckets outpace serialized asset rows.

    Individual-mode asset rows only flip AVAILABLE->ISSUED at handover, so a unit
    that is accepted-but-not-yet-issued still leaves its asset row AVAILABLE while
    `reserved_quantity` is incremented. Counting AVAILABLE assets alone would let a
    drifted-high quantity bucket reserve the same physical asset for two requests;
    subtract the already-reserved (committed-but-unissued) units so the available
    physical assets must cover this request PLUS every outstanding reservation."""
    required_qty = int(required_qty)
    if product.tracking_mode != TrackingMode.INDIVIDUAL or required_qty <= 0:
        return

    available_assets = InventoryAsset.objects.filter(
        product_id=product.pk,
        status=InventoryAsset.Status.AVAILABLE,
    ).count()
    already_reserved = max(int(getattr(product, "reserved_quantity", 0) or 0), 0)
    if available_assets < required_qty + already_reserved:
        raise InsufficientStock(
            f"Insufficient available assets for product {product.pk}: "
            f"requested {required_qty}, already reserved {already_reserved}, "
            f"available assets {available_assets}."
        )


# Dispositions for units rejected as broken at handover.
REJECT_NEEDS_FIX = "needs_fix"  # park on the to-be-fixed shelf (stays in total)
REJECT_REMOVE = "remove"  # scrap it out of inventory entirely (total drops)


def issue_items(request, rejects_by_item=None):
    """Move each accepted item out of `reserved`.

    `rejects_by_item` maps HardwareRequestItem.id -> (broken, disposition) for units
    rejected as broken at handover. Broken units leave `reserved`; with disposition
    'needs_fix' they go to the needs-fix shelf (stays within total), with 'remove' they
    are scrapped (total drops). The rest of the accepted quantity is issued normally.
    """
    if not connection.in_atomic_block:
        raise RuntimeError("issue_items must be called inside transaction.atomic().")

    rejects_by_item = rejects_by_item or {}
    items = list(request.items.order_by("product_id"))
    product_ids = [item.product_id for item in items]
    products = {
        product.pk: product
        for product in InventoryProduct.objects.select_for_update()
        .filter(pk__in=product_ids)
        .order_by("pk")
    }

    for item in items:
        accepted = item.accepted_quantity
        if accepted <= 0:
            continue

        broken, disposition = rejects_by_item.get(item.id, (0, REJECT_NEEDS_FIX))
        broken = max(0, int(broken))
        if broken > accepted:
            raise InsufficientStock(
                f"Cannot reject {broken} as broken: only {accepted} accepted."
            )
        issued = accepted - broken

        product = products[item.product_id]
        if product.reserved_quantity < accepted:
            raise InsufficientStock(
                f"Insufficient reserved stock for product {product.pk}: "
                f"requested {accepted}, reserved {product.reserved_quantity}."
            )

        product.reserved_quantity -= accepted
        product.issued_quantity += issued
        update_fields = ["reserved_quantity", "issued_quantity", "updated_at"]
        if broken and disposition == REJECT_REMOVE:
            product.total_quantity -= broken
            update_fields.append("total_quantity")
        elif broken:
            product.needs_fix_quantity += broken
            update_fields.append("needs_fix_quantity")
        product.save(update_fields=update_fields)

        item.issued_quantity = issued
        item.needs_fix_quantity = 0 if disposition == REJECT_REMOVE else broken
        item.save(update_fields=["issued_quantity", "needs_fix_quantity"])


def repair_from_needs_fix(product, quantity):
    """Move repaired units off the to-be-fixed shelf back into available stock."""
    if not connection.in_atomic_block:
        raise RuntimeError("repair_from_needs_fix must be called inside transaction.atomic().")
    locked = InventoryProduct.objects.select_for_update().get(pk=product.pk)
    if quantity <= 0 or locked.needs_fix_quantity < quantity:
        raise InsufficientStock(
            f"Cannot repair {quantity}: only {locked.needs_fix_quantity} on the shelf."
        )
    locked.needs_fix_quantity -= quantity
    locked.available_quantity += quantity
    locked.save(update_fields=["needs_fix_quantity", "available_quantity", "updated_at"])
    return locked

def move_available_to_needs_fix(product, quantity):
    """Move available units out of circulation onto the to-be-fixed shelf."""
    if not connection.in_atomic_block:
        raise RuntimeError("move_available_to_needs_fix must be called inside transaction.atomic().")
    locked = InventoryProduct.objects.select_for_update().get(pk=product.pk)
    if quantity <= 0 or locked.available_quantity < quantity:
        raise InsufficientStock(
            f"Cannot move {quantity}: only {locked.available_quantity} available."
        )
    locked.available_quantity -= quantity
    locked.needs_fix_quantity += quantity
    locked.save(update_fields=["available_quantity", "needs_fix_quantity", "updated_at"])
    return locked

def scrap_from_needs_fix(product, quantity):
    """Remove unrepairable units from the to-be-fixed shelf and from inventory (total drops)."""
    if not connection.in_atomic_block:
        raise RuntimeError("scrap_from_needs_fix must be called inside transaction.atomic().")
    locked = InventoryProduct.objects.select_for_update().get(pk=product.pk)
    if quantity <= 0 or locked.needs_fix_quantity < quantity:
        raise InsufficientStock(
            f"Cannot scrap {quantity}: only {locked.needs_fix_quantity} on the shelf."
        )
    locked.needs_fix_quantity -= quantity
    locked.total_quantity -= quantity
    locked.save(update_fields=["needs_fix_quantity", "total_quantity", "updated_at"])
    return locked


def return_items(request, resolutions):
    if not connection.in_atomic_block:
        raise RuntimeError("return_items must be called inside transaction.atomic().")

    items = [resolution["item"] for resolution in resolutions]
    product_ids = [item.product_id for item in items]
    products = {
        product.pk: product
        for product in InventoryProduct.objects.select_for_update()
        .filter(pk__in=product_ids)
        .order_by("pk")
    }

    for resolution in resolutions:
        item = resolution["item"]
        returned = resolution["returned"]
        damaged = resolution["damaged"]
        missing = resolution["missing"]
        quantity = returned + damaged + missing
        if quantity <= 0:
            continue

        product = products[item.product_id]
        if product.issued_quantity < quantity:
            raise InsufficientStock(
                f"Insufficient issued stock for product {product.pk}: "
                f"returning {quantity}, issued {product.issued_quantity}."
            )

        product.issued_quantity -= quantity
        product.available_quantity += returned
        product.damaged_quantity += damaged
        product.lost_quantity += missing
        product.save(
            update_fields=[
                "issued_quantity",
                "available_quantity",
                "damaged_quantity",
                "lost_quantity",
                "updated_at",
            ]
        )

        item.returned_quantity += returned
        item.damaged_quantity += damaged
        item.missing_quantity += missing
        item.save(
            update_fields=[
                "returned_quantity",
                "damaged_quantity",
                "missing_quantity",
            ]
        )
