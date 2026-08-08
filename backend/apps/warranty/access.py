from django.shortcuts import get_object_or_404
from rest_framework.exceptions import PermissionDenied

from apps.accounts import rbac
from apps.admin_api.permissions import require_action
from apps.inventory.models import InventoryAsset
from apps.makerspaces.guards import require_module
from apps.machines import access as machine_access
from apps.machines.models import Machine
from apps.warranty.models import Warranty, WarrantyDocument


def resolve_asset_host(user, asset_pk):
    return get_object_or_404(
        rbac.scope_by_makerspace(
            user,
            InventoryAsset.objects.select_related("makerspace"),
        ),
        pk=asset_pk,
    )



def resolve_machine_host(user, machine_pk):
    return get_object_or_404(
        rbac.scope_by_makerspace(
            user,
            Machine.objects.select_related("makerspace", "machine_type"),
        ),
        pk=machine_pk,
    )


def resolve_warranty(user, warranty_pk):
    return get_object_or_404(
        rbac.scope_by_makerspace(
            user,
            Warranty.objects.select_related("makerspace", "asset", "machine"),
            "makerspace_id",
        ),
        pk=warranty_pk,
    )


def resolve_document(user, doc_pk):
    return get_object_or_404(
        rbac.scope_by_makerspace(
            user,
            WarrantyDocument.objects.select_related(
                "warranty",
                "warranty__asset",
                "warranty__machine",
                "warranty__machine__machine_type",
            ),
            "warranty__makerspace_id",
        ),
        pk=doc_pk,
    )


def action_and_module_for_warranty(warranty):
    if warranty.asset_id:
        return rbac.Action.EDIT_INVENTORY, "staff_admin"
    return rbac.Action.MANAGE_PRINTING, "printing"


def enforce(user, warranty):
    if warranty.machine_id:
        if not machine_access.can_manage_machine(user, warranty.machine):
            raise PermissionDenied()
        require_module(warranty.makerspace_id, "machines")
        return
    action, module = action_and_module_for_warranty(warranty)
    require_action(user, action, warranty.makerspace_id)
    require_module(warranty.makerspace_id, module)
