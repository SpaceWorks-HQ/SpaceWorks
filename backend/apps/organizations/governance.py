"""Organization-only authority, kept separate from makerspace RBAC grants."""

from apps.accounts.models import User


MANAGE_ORGANIZATION_PROFILE = "manage_organization_profile"
MANAGE_ORGANIZATION_MEMBERS = "manage_organization_members"
GOVERNANCE_ACTIONS = frozenset(
    {MANAGE_ORGANIZATION_PROFILE, MANAGE_ORGANIZATION_MEMBERS}
)


def actions_for_membership(membership) -> set[str]:
    if membership is None or membership.status != membership.Status.ACTIVE:
        return set()
    value = membership.governance_actions
    if not isinstance(value, list):
        return set()
    return {
        action
        for action in value
        if isinstance(action, str) and action in GOVERNANCE_ACTIONS
    }


def actions_for(actor, organization) -> set[str]:
    if actor is None or not getattr(actor, "is_authenticated", False):
        return set()
    if actor.is_superuser or actor.role == User.Role.SUPERADMIN:
        return set(GOVERNANCE_ACTIONS)
    if not organization.is_active:
        return set()
    membership = organization.memberships.filter(
        user=actor,
        status="active",
    ).first()
    return actions_for_membership(membership)


def has_any_governance(actor) -> bool:
    if actor is None or not getattr(actor, "is_authenticated", False):
        return False
    if actor.is_superuser or actor.role == User.Role.SUPERADMIN:
        return True
    from apps.organizations.models import OrganizationMembership

    queryset = OrganizationMembership.objects.filter(
        user=actor,
        status=OrganizationMembership.Status.ACTIVE,
        organization__is_active=True,
    )
    from django.db.models import Q

    action_filter = Q()
    for action in GOVERNANCE_ACTIONS:
        action_filter |= Q(governance_actions__contains=[action])
    return queryset.filter(action_filter).exists()
