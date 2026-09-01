from django.db import transaction
from django.http import Http404
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.admin_api.serializers_inventory import InventoryProductAdminCreateSerializer
from apps.admin_api.views_inventory import _assert_box_in_makerspace, _assert_category_in_makerspace
from apps.audit import services as audit
from apps.inventory import availability
from apps.inventory.models import InventoryProduct
from apps.procurement.models import ToBuyItem


class MoveMode:
    CREATE = "create"
    TOPUP = "topup"


class PrintingTarget:
    SPOOL = "spool"
    PRINTER = "printer"


def move_to_inventory(
    actor,
    item,
    *,
    mode,
    product_id=None,
    quantity,
    box_id=None,
    category_id=None,
    tracking_mode=None,
    is_public,
    public_availability_mode,
    show_public_count,
    public_self_checkout_enabled,
    name=None,
    description="",
):
    with transaction.atomic():
        locked = ToBuyItem.objects.select_for_update().select_related("makerspace").get(pk=item.pk)
        _assert_move_allowed(locked, ToBuyItem.Kind.HARDWARE)
        quantity = _positive_quantity(quantity)

        if mode == MoveMode.CREATE:
            product = _create_inventory_product(
                locked,
                box_id=box_id,
                category_id=category_id,
                tracking_mode=tracking_mode,
                is_public=is_public,
                public_availability_mode=public_availability_mode,
                show_public_count=show_public_count,
                public_self_checkout_enabled=public_self_checkout_enabled,
                name=name,
                description=description,
            )
        elif mode == MoveMode.TOPUP:
            product = _topup_product(locked, product_id)
        else:
            raise ValidationError({"mode": "Use create or topup."})

        try:
            product = availability.adjust_quantities(
                product,
                delta_available=quantity,
                delta_damaged=0,
                delta_lost=0,
                reason=f"Received from to-buy #{locked.id}",
                actor=actor,
            )
        except availability.InsufficientStock as exc:
            raise ValidationError({"quantity": str(exc)}) from exc

        locked.moved_to_inventory_at = timezone.now()
        locked.resulting_product = product
        locked.save(update_fields=["moved_to_inventory_at", "resulting_product", "updated_at"])
        audit.record(
            actor,
            "procurement.moved_to_inventory",
            makerspace=locked.makerspace,
            target=locked,
            meta={
                "item_id": locked.id,
                "product_id": product.id,
                "quantity": quantity,
                "mode": mode,
            },
        )
        return product


def move_to_printing(actor, item, *, target, data):
    with transaction.atomic():
        # `machine_type` is deliberately NOT select_related here: it is nullable, so
        # Django emits a LEFT OUTER JOIN and Postgres refuses outright --
        # "FOR UPDATE cannot be applied to the nullable side of an outer join". The
        # attribute is read a few lines down and lazy-loads in one extra query, which is
        # free next to the writes this transaction already performs. `makerspace` is
        # non-nullable, so its INNER JOIN is fine to lock against.
        locked = ToBuyItem.objects.select_for_update().select_related(
            "makerspace"
        ).get(pk=item.pk)
        _assert_move_allowed(locked, ToBuyItem.Kind.PRINTING)
        from apps.machines.procurement import move_received_printing
        result = move_received_printing(
            locked.makerspace,
            actor,
            target=target,
            data=data,
            machine_type=locked.machine_type,
        )
        if target == PrintingTarget.SPOOL:
            locked.resulting_pool = result
            update_fields = ["moved_to_inventory_at", "resulting_pool", "updated_at"]
        elif target == PrintingTarget.PRINTER:
            locked.resulting_machine = result
            update_fields = ["moved_to_inventory_at", "resulting_machine", "updated_at"]
        else:
            raise ValidationError({"target": "Use spool or printer."})
        locked.moved_to_inventory_at = timezone.now()
        locked.save(update_fields=update_fields)
        audit.record(actor, "procurement.moved_to_printing", makerspace=locked.makerspace, target=locked, meta={"item_id": locked.id, "target": target, "result_id": result.id, "kernel": True})
        return result

def _assert_move_allowed(item, expected_kind):
    if item.kind != expected_kind:
        raise ValidationError({"kind": f"Item must be {expected_kind}."})
    if item.status != ToBuyItem.Status.RECEIVED:
        raise ValidationError({"status": "Item must be received before it can be moved."})
    if item.moved_to_inventory_at is not None:
        raise ValidationError({"detail": "Already moved to inventory."})


def _positive_quantity(value):
    try:
        quantity = int(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError({"quantity": "Quantity must be a positive integer."}) from exc
    if quantity < 1:
        raise ValidationError({"quantity": "Quantity must be at least 1."})
    return quantity


def _create_inventory_product(
    item,
    *,
    box_id,
    category_id,
    tracking_mode,
    is_public,
    public_availability_mode,
    show_public_count,
    public_self_checkout_enabled,
    name,
    description,
):
    payload = {
        "name": (name or "").strip(),
        "description": description or "",
        "box": box_id,
        "category": category_id,
        "tracking_mode": tracking_mode,
        "is_public": is_public,
        "public_availability_mode": public_availability_mode,
        "show_public_count": show_public_count,
        "public_self_checkout_enabled": public_self_checkout_enabled,
    }
    serializer = InventoryProductAdminCreateSerializer(data=payload)
    serializer.is_valid(raise_exception=True)
    _assert_box_in_makerspace(serializer.validated_data.get("box"), item.makerspace_id)
    _assert_category_in_makerspace(serializer.validated_data.get("category"), item.makerspace_id)
    return serializer.save(makerspace=item.makerspace)


def _topup_product(item, product_id):
    if not product_id:
        raise ValidationError({"product_id": "This field is required for topup."})
    try:
        return InventoryProduct.objects.select_related("makerspace").get(
            pk=product_id,
            makerspace_id=item.makerspace_id,
        )
    except InventoryProduct.DoesNotExist as exc:
        raise Http404() from exc
