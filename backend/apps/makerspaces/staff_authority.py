"""Locked revalidation for staff actions that mint authority for another person."""

from dataclasses import dataclass

from django.db import connection
from rest_framework.exceptions import PermissionDenied

from apps.accounts import rbac
from apps.accounts.models import User
from apps.makerspaces.models import Makerspace, MakerspaceMembership, MakerspaceRole


@dataclass(frozen=True)
class LockedStaffAuthority:
    makerspace: Makerspace
    actor: User
    membership: MakerspaceMembership | None
    role: MakerspaceRole | None


def lock_and_validate_staff_authority(
    *, actor, makerspace_id: int, allowed_actions: frozenset[str]
) -> LockedStaffAuthority:
    """Lock authority in makerspace → user → membership → role order and revalidate it.

    This helper is shared with the witnessed-waiver work at integration. Keep its
    signature and lock order aligned there rather than copying either authorization rule.
    The caller must already be inside ``transaction.atomic()``.
    """
    if not connection.in_atomic_block:
        raise RuntimeError("Staff authority must be validated inside transaction.atomic().")

    makerspace = Makerspace.objects.select_for_update().filter(pk=makerspace_id).first()
    if makerspace is None:
        raise PermissionDenied()
    locked_actor = User.objects.select_for_update().filter(pk=actor.pk).first()
    if locked_actor is None:
        raise PermissionDenied()
    if (
        not locked_actor.is_active
        or locked_actor.access_status != User.AccessStatus.ACTIVE
        or locked_actor.must_change_password
        or makerspace.archived_at is not None
    ):
        raise PermissionDenied()

    membership = (
        MakerspaceMembership.objects.select_for_update()
        .filter(user=locked_actor, makerspace=makerspace, status="active")
        .first()
    )
    role = None
    if membership is not None and membership.assigned_role_id is not None:
        role = MakerspaceRole.objects.select_for_update().get(
            pk=membership.assigned_role_id
        )
        membership.assigned_role = role

    is_global_superadmin = bool(
        locked_actor.is_superuser or locked_actor.role == User.Role.SUPERADMIN
    )
    if is_global_superadmin and makerspace.superadmin_access_enabled:
        effective_actions = set(rbac.ROLE_GRANTABLE_ACTIONS)
    else:
        effective_actions = rbac.actions_for_membership(membership)
    if not effective_actions.intersection(allowed_actions):
        raise PermissionDenied()

    return LockedStaffAuthority(makerspace, locked_actor, membership, role)
