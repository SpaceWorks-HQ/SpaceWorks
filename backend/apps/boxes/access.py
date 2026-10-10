from django.shortcuts import get_object_or_404

from apps.accounts import rbac
from apps.boxes.models import QrCode
from apps.inventory.models import InventoryAsset, InventoryProduct
from apps.makerspaces.models import Makerspace


def makerspace_for_action(user, action, makerspace_id):
    queryset = rbac.scope_by_action(user, action, Makerspace.objects.all(), field="id")
    return get_object_or_404(queryset, pk=makerspace_id)


def inventory_qr_codes(queryset=None):
    """Every QR an INVENTORY surface may touch: all of them except member cards.

    A member-card QR is an identity credential under `manage_member_cards`, resolved
    only by `member_card_services.resolve`. Every generic QR path -- scan, print,
    revoke, rebind, stocktake, self-checkout, direct handout -- filters through here,
    so an inventory role can neither read a person from a card nor revoke, rebind or
    check out against one (a member-card `target_id` is a MemberCard pk, which other
    paths would otherwise read as a Box or product pk).
    """
    queryset = QrCode.objects.all() if queryset is None else queryset
    return queryset.exclude(target_type=QrCode.TargetType.MEMBER_CARD)


def qr_for_action(user, action, **filters):
    queryset = rbac.scope_by_action(user, action, inventory_qr_codes())
    return get_object_or_404(queryset, **filters)


def locked_qr_for_action(user, action, **filters):
    queryset = rbac.scope_by_action(
        user, action, inventory_qr_codes(QrCode.objects.select_for_update())
    )
    return get_object_or_404(queryset, **filters)


def target_for_rebind(user, target_type, target_id):
    action = rbac.Action.EDIT_INVENTORY
    if target_type == QrCode.TargetType.PRODUCT:
        queryset = rbac.scope_by_action(user, action, InventoryProduct.objects.select_for_update())
    else:
        queryset = rbac.scope_by_action(user, action, InventoryAsset.objects.select_for_update())
    return get_object_or_404(queryset, pk=target_id)
