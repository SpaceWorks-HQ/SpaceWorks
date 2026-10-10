"""Locked role assignment and community-only roster delegation."""

from django.db import transaction
from rest_framework.exceptions import PermissionDenied

from apps.accounts import rbac
from apps.audit import services as audit
from apps.makerspaces.models import Makerspace, MakerspaceMembership, MakerspaceRole


def can_assign_role(actor, makerspace, role, target_membership=None):
    """Raise on a role assignment that would let a local manager escalate."""
    if role.makerspace_id != makerspace.id:
        raise PermissionDenied()
    from apps.makerspaces.role_authority import _clean_actions, _locked_actor_actions, _superadmin

    actions = _clean_actions(role.granted_actions)
    actor_actions = _locked_actor_actions(actor, makerspace)
    if rbac.Action.MANAGE_MAKERSPACE not in actor_actions:
        # Roster delegation confers community assignment, never staff administration.
        if (rbac.Action.MANAGE_MEMBERS not in actor_actions or actions
                or (target_membership and rbac.actions_for_membership(target_membership))):
            raise PermissionDenied()
        return True
    if _superadmin(actor):
        return True
    if target_membership and rbac.Action.MANAGE_MAKERSPACE in rbac.actions_for_membership(target_membership):
        raise PermissionDenied()
    if rbac.Action.MANAGE_MAKERSPACE in actions or not actions <= (
        actor_actions - {rbac.Action.MANAGE_MAKERSPACE}
    ):
        raise PermissionDenied()
    return True


def assign_role(*, makerspace, actor, membership, role):
    """Atomically assign a makerspace role and preserve the legacy role mirror."""
    if role.makerspace_id != makerspace.id or membership.makerspace_id != makerspace.id:
        raise PermissionDenied()
    with transaction.atomic():
        makerspace = Makerspace.objects.select_for_update().get(pk=makerspace.pk)
        role = MakerspaceRole.objects.select_for_update().get(
            pk=role.pk, makerspace=makerspace
        )
        membership = (
            MakerspaceMembership.objects.select_for_update(of=("self",))
            .select_related("assigned_role")
            .get(pk=membership.pk)
        )
        if membership.makerspace_id != makerspace.id:
            raise PermissionDenied()
        can_assign_role(actor, makerspace, role, target_membership=membership)
        old_role_id = membership.assigned_role_id
        membership.assigned_role = role
        membership.role = role.legacy_role or MakerspaceMembership.Role.CUSTOM
        membership.save(update_fields=["assigned_role", "role"])
        audit.record(
            actor,
            "staff.role_assigned",
            makerspace=makerspace,
            target=membership.user,
            meta={
                "membership_id": membership.id,
                "old_role_id": old_role_id,
                "new_role_id": role.id,
                "new_role_slug": role.slug,
            },
        )
        return membership


