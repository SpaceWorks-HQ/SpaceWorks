"""Transactional staff-authority revalidation for high-trust desk actions."""

from django.db import connection
from rest_framework.exceptions import PermissionDenied

from apps.accounts import rbac
from apps.accounts.models import User
from apps.makerspaces.models import Makerspace, MakerspaceMembership, MakerspaceRole


def lock_staff_authority(actor, makerspace_id, allowed_actions):
    """Lock and revalidate staff authority in the canonical order.

    Witnessed waiver acceptance and the later claim-code issuance path must share this
    contract so active status, restrictions, temporary passwords, and role grants cannot
    drift between two credential/evidence writers. Call only inside ``atomic()``.
    """
    if not connection.in_atomic_block:
        raise RuntimeError("Staff authority must be checked inside a transaction.")

    makerspace = Makerspace.objects.select_for_update().get(pk=makerspace_id)
    if makerspace.archived_at is not None:
        raise PermissionDenied()
    locked_actor = User.objects.select_for_update().get(pk=actor.pk)
    if (
        not locked_actor.is_active
        or locked_actor.access_status != User.AccessStatus.ACTIVE
        or locked_actor.must_change_password
    ):
        raise PermissionDenied()

    membership = (
        MakerspaceMembership.objects.select_for_update(of=("self",))
        .filter(makerspace=makerspace, user=locked_actor)
        .first()
    )
    if membership and membership.assigned_role_id:
        membership.assigned_role = MakerspaceRole.objects.select_for_update().get(
            pk=membership.assigned_role_id
        )

    is_global_superadmin = locked_actor.is_superuser or (
        locked_actor.role == User.Role.SUPERADMIN
    )
    if is_global_superadmin and makerspace.superadmin_access_enabled:
        actions = set(rbac.ROLE_GRANTABLE_ACTIONS)
    else:
        actions = rbac.actions_for_membership(membership)
    if not actions.intersection(allowed_actions):
        raise PermissionDenied()
    return makerspace, locked_actor, membership, actions
