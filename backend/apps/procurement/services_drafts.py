"""Audited hardware procurement drafts; inventory suggestions use this same seam."""

from django.db import transaction
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.accounts import rbac
from apps.audit import services as audit
from apps.inventory.models import InventoryProduct
from apps.makerspaces.guards import require_module_locked
from apps.procurement import access
from apps.procurement.models import ToBuyItem


@transaction.atomic
def create_hardware_draft(actor, makerspace, *, name, quantity, vendor_name="", source_product=None):
    makerspace = require_module_locked(makerspace, "procurement")
    if not access.can_manage_kind(actor, makerspace.pk, ToBuyItem.Kind.HARDWARE):
        raise PermissionDenied()
    name = str(name).strip()
    vendor_name = str(vendor_name).strip()
    if type(quantity) is not int or not 1 <= quantity <= 2147483647 or not name:
        raise ValidationError("A name and positive quantity are required.")
    if len(name) > 200 or len(vendor_name) > 200:
        raise ValidationError("Name and supplier must be at most 200 characters.")
    if source_product is not None and not rbac.scope_by_action(
        actor, rbac.Action.EDIT_INVENTORY, InventoryProduct.objects.all(),
    ).filter(pk=source_product.pk, makerspace=makerspace, is_archived=False).exists():
        raise ValidationError("Source product must belong to this makerspace.")
    item = ToBuyItem.objects.create(
        makerspace=makerspace, kind=ToBuyItem.Kind.HARDWARE, status=ToBuyItem.Status.REQUESTED,
        name=name, quantity=quantity, vendor_name=vendor_name,
        source_product=source_product, created_by=actor,
    )
    audit.record(actor, "procurement.item_added", makerspace=makerspace, target=item)
    return item


@transaction.atomic
def create_reorder_draft(actor, makerspace, product_id):
    from django.shortcuts import get_object_or_404

    makerspace = require_module_locked(makerspace, "procurement")
    if not access.can_manage_kind(actor, makerspace.pk, ToBuyItem.Kind.HARDWARE):
        raise PermissionDenied()
    product = get_object_or_404(rbac.scope_by_action(
        actor, rbac.Action.EDIT_INVENTORY,
        InventoryProduct.objects.select_for_update().filter(makerspace=makerspace, is_archived=False),
    ), pk=product_id)
    if product.reorder_point <= 0 or product.available_quantity > product.reorder_point:
        raise ValidationError("This product is not at its reorder point.")
    if product.reorder_quantity <= 0:
        raise ValidationError("Set a positive reorder quantity before creating a draft.")
    existing = access.scope_items(
        rbac.scope_by_action(actor, rbac.Action.EDIT_INVENTORY, ToBuyItem.objects.all()), actor, makerspace.pk,
    ).filter(source_product=product, kind=ToBuyItem.Kind.HARDWARE, status__in=[
        ToBuyItem.Status.REQUESTED, ToBuyItem.Status.APPROVED, ToBuyItem.Status.ORDERED,
        ToBuyItem.Status.RECEIVED,
    ], moved_to_inventory_at__isnull=True).first()
    if existing:
        return existing, False
    item = create_hardware_draft(actor, makerspace, name=product.name,
                                 quantity=product.reorder_quantity, vendor_name=product.supplier,
                                 source_product=product)
    return item, True
