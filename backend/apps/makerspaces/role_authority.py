"""Locked authority and validation for per-makerspace role mutations."""

from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.accounts import rbac
from apps.accounts.models import User
from apps.makerspaces.models import Makerspace, MakerspaceMembership, MakerspaceRole
from apps.organizations.models import (
    Organization,
    OrganizationMakerspace,
)

# The protected community role every activation path assigns (`roles.MEMBER_ROLE_DEFINITION`).
MEMBER_ROLE_SLUG = "member"


class RoleConflict(Exception):
    """A role cannot be deleted (protected, or still assigned to a membership).

    Plain exception (not a DRF APIException) so the project's
    ``workflow_exception_handler`` maps it to the structured ``{detail, code}``
    body via ``_EXCEPTION_MAP`` instead of DRF's bare ``{detail}`` default."""


def _superadmin(actor):
    return actor.is_superuser or actor.role == User.Role.SUPERADMIN


def _locked_actor_actions(actor, makerspace):
    membership = (
        MakerspaceMembership.objects.select_for_update(of=("self",))
        .select_related("assigned_role")
        .filter(makerspace=makerspace, user=actor, status="active")
        .first()
    )
    if membership and membership.assigned_role_id:
        membership.assigned_role = MakerspaceRole.objects.select_for_update().get(
            pk=membership.assigned_role_id
        )
    if _superadmin(actor) and makerspace.superadmin_access_enabled:
        return set(rbac.ROLE_GRANTABLE_ACTIONS)
    return rbac.actions_for_membership(membership) | _locked_organization_actions(
        actor, makerspace
    )


def _locked_organization_actions(actor, makerspace):
    """Revalidate organization authority under locks before role mutations."""
    # Resolve candidate parent/child ids without holding either row class. The locked
    # reads below then follow Django admin's parent-first save order.
    resolved_links = list(
        OrganizationMakerspace.objects
        .filter(makerspace=makerspace)
        .values_list("organization_id", "pk")
        .order_by("pk")
    )
    organization_ids = sorted(
        {organization_id for organization_id, _ in resolved_links}
    )
    if not organization_ids:
        return set()

    # Final organization-authority lock order: Organization rows (ascending pk),
    # then OrganizationMakerspace rows (ascending pk), then OrganizationMembership
    # rows (ascending pk). Django admin takes the same parent-before-child order.
    locked_organizations = list(
        Organization.objects.select_for_update()
        .filter(pk__in=organization_ids)
        .order_by("pk")
    )
    locked_organization_ids = [
        organization.pk for organization in locked_organizations
    ]
    locked_links = list(
        OrganizationMakerspace.objects.select_for_update()
        .filter(
            pk__in=[link_id for _, link_id in resolved_links],
            organization_id__in=locked_organization_ids,
            makerspace=makerspace,
        )
        .order_by("pk")
    )
    if not locked_links:
        return set()
    locked_link_ids = [link.pk for link in locked_links]
    locked_organization_ids = sorted(
        {link.organization_id for link in locked_links}
    )
    memberships = (
        rbac._organization_authority_memberships(
            actor, makerspace_ids=[makerspace.pk]
        )
        .filter(
            organization_id__in=locked_organization_ids,
            organization__makerspace_links__pk__in=locked_link_ids,
        )
        .select_for_update(of=("self",))
        .select_related("organization")
        .order_by("pk")
    )
    actions = set()
    for membership in memberships:
        actions.update(rbac.actions_for_organization_membership(membership))
    return actions


def _clean_actions(actions):
    if not isinstance(actions, list) or any(not isinstance(item, str) for item in actions):
        raise ValidationError({"granted_actions": "Use a list of action values."})
    values = set(actions)
    if values & rbac.ROLE_FORBIDDEN_ACTIONS:
        raise ValidationError(
            {"granted_actions": "This action cannot be granted to a makerspace role."}
        )
    unknown = values - rbac.ALL_ACTIONS
    if unknown:
        raise ValidationError({"granted_actions": "Unknown action value."})
    return values


def _validate_actions(actor, makerspace, actions, role=None):
    values = _clean_actions(actions)
    is_superadmin = _superadmin(actor)
    actor_actions = _locked_actor_actions(actor, makerspace)
    if rbac.Action.MANAGE_MAKERSPACE not in actor_actions:
        raise PermissionDenied()
    if not is_superadmin:
        ceiling = actor_actions - {rbac.Action.MANAGE_MAKERSPACE}
        if not values <= ceiling:
            raise PermissionDenied()
    if role and role.legacy_role == MakerspaceMembership.Role.SPACE_MANAGER:
        if rbac.Action.MANAGE_MAKERSPACE not in values:
            raise ValidationError(
                {"granted_actions": "The Space Manager role must retain manage_makerspace."}
            )
    if role and role.is_protected and role.slug == MEMBER_ROLE_SLUG and values:
        # Every open join, referral claim, walk-in and imported adoption activates onto
        # this role, and `invite_membership` reads "grants no actions" as "community
        # invitation". An action here would hand staff authority to all of them and turn
        # the module gate on community invitations into a bypass.
        raise ValidationError({"granted_actions": "The Member role grants no staff actions."})
    # No Guest Admin ceiling any more: migration 0052 retired it as a built-in, so the
    # handover role is an ordinary custom role and is bounded by the general rule above --
    # you cannot grant an action you do not hold yourself. `rbac.HANDOUT_ACTIONS` survives
    # as the definition of "handover-only" for `is_handout_only`, which decides what the
    # console shows such a staffer; it is no longer a cap on what any role may hold.
    return sorted(values)


