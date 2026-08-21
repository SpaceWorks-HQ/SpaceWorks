"""Superadmin visibility and hard-hide RBAC helpers."""

from django.db.models import F

from apps.accounts.models import User

from .rbac_actions import (
    ROLE_FORBIDDEN_ACTIONS,
    _action_scope_filters,
    actions_for_membership,
)
from .rbac_memberships import _membership_for


def superadmin_hidden_makerspace_ids():
    from apps.makerspaces.models import Makerspace

    return set(
        Makerspace.objects.filter(
            superadmin_access_enabled=False,
        )
        .values_list("id", flat=True)
    )


def _id_in(makerspace_id, ids):
    if makerspace_id in ids:
        return True
    try:
        return int(makerspace_id) in ids
    except (TypeError, ValueError):
        return False


def _is_superadmin(actor):
    return bool(
        actor is not None
        and getattr(actor, "is_authenticated", False)
        and (actor.is_superuser or actor.role == User.Role.SUPERADMIN)
    )


def _superadmin_hidden_to_exclude(actor, action=None):
    """Hidden makerspace ids a GLOBAL superadmin must be cut off from.

    A makerspace with superadmin_access_enabled=False is excluded UNLESS the
    superadmin holds an explicit MakerspaceMembership there (granting `action`,
    when given) -- a superadmin who is also a real member keeps that membership's
    role-scoped access, but never global superpower (review fix #2)."""
    hidden = superadmin_hidden_makerspace_ids()
    if not hidden:
        return set()
    memberships = actor.makerspace_memberships.filter(
        makerspace_id__in=hidden,
        status="active",
    )
    if action is None:
        member_ok = set(memberships.values_list("makerspace_id", flat=True))
    elif action in ROLE_FORBIDDEN_ACTIONS:
        member_ok = set()
    else:
        assigned_filter, legacy_roles = _action_scope_filters(action)
        assigned_ok = set(
            memberships.filter(
                assigned_role__isnull=False,
                assigned_role__makerspace=F("makerspace"),
            ).filter(assigned_filter).values_list("makerspace_id", flat=True)
        )
        legacy_ok = (
            set(
                memberships.filter(
                    assigned_role__isnull=True,
                    role__in=legacy_roles,
                ).values_list("makerspace_id", flat=True)
            )
            if legacy_roles
            else set()
        )
        member_ok = assigned_ok | legacy_ok
    return hidden - member_ok


def superadmin_hidden_to_exclude_without_servability(actor, action=None):
    """Return hard-hide exclusions while deliberately omitting servability."""
    return _superadmin_hidden_to_exclude(actor, action)


def superadmin_hidden_block_applies(actor, makerspace_id, action=None):
    """True when a global superadmin must be HARD-blocked from `makerspace_id`."""
    if not _is_superadmin(actor) or makerspace_id is None:
        return False
    if not _id_in(makerspace_id, superadmin_hidden_makerspace_ids()):
        return False
    membership = _membership_for(actor, makerspace_id)
    if membership is None:
        return True  # no membership -> global superpower is withheld
    if action is None:
        return False  # legitimate member: membership role governs, not blocked
    return action not in actions_for_membership(membership)


def hide_from_superadmin(actor, queryset, field="makerspace_id"):
    """Exclude hard-hidden makerspaces for a global superadmin. Delegates to the
    same policy as the RBAC scopes so a superadmin who is an explicit member of a
    hidden space is NOT excluded (no contradiction with scope_by_action)."""
    if not _is_superadmin(actor):
        return queryset
    excluded = _superadmin_hidden_to_exclude(actor, None)
    if not excluded:
        return queryset
    return queryset.exclude(**{f"{field}__in": excluded})
