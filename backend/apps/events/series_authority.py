from django.db.models import Q

from apps.accounts import rbac
from apps.accounts.models import User
from apps.organizations.models import OrganizationMembership


def _is_superadmin(actor):
    return bool(
        actor and getattr(actor, "is_authenticated", False)
        and (actor.is_superuser or actor.role == User.Role.SUPERADMIN)
    )


def organizer_series_q(actor, *, prefix=""):
    if actor is None or not getattr(actor, "is_authenticated", False) or _is_superadmin(actor):
        return Q(pk__in=[])
    organization = f"{prefix}organizers__organization"
    membership = f"{organization}__memberships"
    actions = Q()
    for action in (
        rbac.actions_satisfying(rbac.Action.MANAGE_EVENTS)
        & rbac.ORGANIZATION_GRANTABLE_ACTIONS
    ):
        actions |= Q(**{f"{membership}__granted_actions__contains": [action]})
    return (
        Q(**{
            f"{organization}__is_active": True,
            f"{membership}__user": actor,
            f"{membership}__status": OrganizationMembership.Status.ACTIVE,
        })
        & actions
        & ~Q(**{f"{prefix}makerspace_id__in": rbac.archived_makerspace_ids()})
    )


def can_manage_series(actor, series):
    if rbac.can(actor, rbac.Action.MANAGE_EVENTS, series.makerspace_id):
        return True
    if _is_superadmin(actor) or series.makerspace_id in rbac.archived_makerspace_ids():
        return False
    memberships = OrganizationMembership.objects.filter(
        user=actor,
        status=OrganizationMembership.Status.ACTIVE,
        organization__is_active=True,
        organization__organized_event_series__series=series,
    )
    return any(
        rbac.Action.MANAGE_EVENTS in rbac.actions_for_organization_membership(row)
        for row in memberships
    )
