"""Read and locked authorization helpers for global organizations."""

from django.db.models import Q
from rest_framework.exceptions import PermissionDenied

from apps.accounts.models import User
from apps.organizations import governance
from apps.organizations.models import Organization, OrganizationMembership


def is_superadmin(actor) -> bool:
    return bool(
        actor
        and getattr(actor, "is_authenticated", False)
        and (actor.is_superuser or actor.role == User.Role.SUPERADMIN)
    )


def visible_organizations(actor):
    queryset = Organization.objects.all()
    if is_superadmin(actor):
        return queryset
    return queryset.filter(
        is_active=True,
        memberships__user=actor,
        memberships__status=OrganizationMembership.Status.ACTIVE,
    ).distinct()


def active_membership(actor, organization):
    if is_superadmin(actor):
        return None
    return OrganizationMembership.objects.filter(
        organization=organization,
        user=actor,
        status=OrganizationMembership.Status.ACTIVE,
        organization__is_active=True,
    ).first()


def require_governance(actor, organization, action):
    if action not in governance.actions_for(actor, organization):
        raise PermissionDenied()


def lock_governance_membership(actor, organization, action):
    """Recheck organization authority under the row changed by governance edits."""
    if is_superadmin(actor):
        return None
    membership = OrganizationMembership.objects.select_for_update().filter(
        organization=organization,
        user=actor,
        status=OrganizationMembership.Status.ACTIVE,
        organization__is_active=True,
    ).first()
    if action not in governance.actions_for_membership(membership):
        raise PermissionDenied()
    return membership


def organization_membership_q(actor):
    """Reusable active-membership predicate for assignable organization lists."""
    if is_superadmin(actor):
        return Q(is_active=True)
    return Q(
        is_active=True,
        memberships__user=actor,
        memberships__status=OrganizationMembership.Status.ACTIVE,
    )
