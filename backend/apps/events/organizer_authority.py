from django.db.models import Q

from apps.accounts import rbac
from apps.accounts.models import User
from apps.organizations.models import OrganizationMembership


def _is_superadmin(actor):
    return bool(
        actor
        and getattr(actor, "is_authenticated", False)
        and (actor.is_superuser or actor.role == User.Role.SUPERADMIN)
    )


def organizer_event_q(actor, *, event_prefix=""):
    """Return the narrow SQL predicate for events organized by this actor's org."""
    if (
        actor is None
        or not getattr(actor, "is_authenticated", False)
        or _is_superadmin(actor)
    ):
        return Q(pk__in=[])

    organization_path = f"{event_prefix}organizers__organization"
    membership_path = f"{organization_path}__memberships"
    action_filter = Q()
    for action in (
        rbac.actions_satisfying(rbac.Action.MANAGE_EVENTS)
        & rbac.ORGANIZATION_GRANTABLE_ACTIONS
    ):
        action_filter |= Q(
            **{f"{membership_path}__granted_actions__contains": [action]}
        )
    if not action_filter:
        return Q(pk__in=[])

    return (
        Q(
            **{
                f"{organization_path}__is_active": True,
                f"{membership_path}__user": actor,
                f"{membership_path}__status": OrganizationMembership.Status.ACTIVE,
            }
        )
        & action_filter
        & ~Q(
            **{
                f"{event_prefix}makerspace_id__in": rbac.archived_makerspace_ids()
            }
        )
    )


def can_manage_event(actor, event) -> bool:
    """Authorize one event without widening authority over its venue."""
    if rbac.can(actor, rbac.Action.MANAGE_EVENTS, event.makerspace_id):
        return True
    if _is_superadmin(actor) or event.makerspace_id in rbac.archived_makerspace_ids():
        return False
    memberships = OrganizationMembership.objects.filter(
        user=actor,
        status=OrganizationMembership.Status.ACTIVE,
        organization__is_active=True,
        organization__organized_events__event=event,
    ).select_related("organization")
    return any(
        rbac.Action.MANAGE_EVENTS
        in rbac.actions_for_organization_membership(membership)
        for membership in memberships
    )
