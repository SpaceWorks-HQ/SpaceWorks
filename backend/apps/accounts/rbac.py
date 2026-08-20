"""Single source of truth for role permissions + makerspace scoping (PRD §4).

The implementation is split by dependency layer; this module keeps the public import
surface stable and owns the path-pinned tenant-servability delegation bodies.
"""

from django.db.models import F

from apps.accounts.models import User

from .rbac_actions import (
    ALL,
    ALL_ACTIONS,
    HANDOUT_ACTIONS,
    IMPLIED_ACTIONS,
    ROLE_FORBIDDEN_ACTIONS,
    ROLE_GRANTABLE_ACTIONS,
    ROLE_SUPERADMIN_ASSIGNABLE_ACTIONS,
    Action,
    _HANDOUT_MUTATIONS,
    _MEMBERSHIP_ROLE_ACTIONS,
    _action_scope_filters,
    actions_for_membership,
    actions_for_organization_membership,
    actions_satisfying,
    expand_implied_actions,
)
from .rbac_memberships import (
    _membership_for,
    _membership_is_space_manager,
    membership_role,
)
from .rbac_organizations import (
    _org_actions_for,
    _organization_authority_memberships,
    _org_scope_for_action,
    has_any_org_authority,
)
from .rbac_superadmin import (
    _id_in,
    _is_superadmin,
    _superadmin_hidden_to_exclude,
    hide_from_superadmin,
    superadmin_hidden_block_applies,
    superadmin_hidden_makerspace_ids,
)


def resolve_scope(actor):
    """Return the set of makerspace ids the actor may act in, or ALL."""
    if actor is None or not getattr(actor, "is_authenticated", False):
        return set()
    if actor.is_superuser or actor.role == User.Role.SUPERADMIN:
        return _superadmin_visible_ids(actor, None)
    # Organization grants confer actions, not identity, so they never widen this
    # action-agnostic scope (or scope_by_makerspace(), which derives from it).
    scope = set(
        actor.makerspace_memberships.filter(status="active").values_list(
            "makerspace_id", flat=True
        )
    )
    return _exclude_archived_ids(scope)


def scope_by_makerspace(actor, queryset, makerspace_field="makerspace_id"):
    """Filter a makerspace-owned queryset to the actor's scope (superadmin: unchanged)."""
    scope = resolve_scope(actor)
    if scope is ALL:
        return queryset
    if not scope:
        return queryset.none()
    return queryset.filter(**{f"{makerspace_field}__in": scope})


def makerspaces_for_action(actor, action):
    """Return makerspace ids where actor's membership role grants action, or ALL."""
    if actor is None or not getattr(actor, "is_authenticated", False):
        return set()
    # Organization grants never enter this superadmin branch: hidden-space authority
    # must continue to come only from an explicit makerspace membership.
    if actor.is_superuser or actor.role == User.Role.SUPERADMIN:
        return _superadmin_visible_ids(actor, action)
    if action in ROLE_FORBIDDEN_ACTIONS:
        return set()
    assigned_filter, legacy_roles = _action_scope_filters(action)
    assigned_scope = set(
        actor.makerspace_memberships.filter(
            status="active",
            assigned_role__isnull=False,
            assigned_role__makerspace=F("makerspace"),
        ).filter(assigned_filter).values_list("makerspace_id", flat=True)
    )
    legacy_scope = (
        set(
            actor.makerspace_memberships.filter(
                status="active",
                assigned_role__isnull=True,
                role__in=legacy_roles,
            ).values_list("makerspace_id", flat=True)
        )
        if legacy_roles
        else set()
    )
    org_scope = _org_scope_for_action(actor, action)
    return _exclude_archived_ids(assigned_scope | legacy_scope | org_scope)


def makerspaces_for_actions(actor, *actions):
    """Union of makerspace scopes across several actions, or ALL.

    A makerspace is included if the actor's membership role grants ANY of the
    given actions there. Used where one console surface is reachable by more
    than one role (e.g. the staff makerspace switcher: VIEW_INVENTORY staff OR
    print managers with only MANAGE_PRINTING)."""
    combined = set()
    for action in actions:
        scope = makerspaces_for_action(actor, action)
        if scope is ALL:
            return ALL
        combined |= scope
    return combined


def scope_by_action(actor, action, queryset, field="makerspace_id"):
    """Filter queryset to makerspaces where actor's membership grants action."""
    scope = makerspaces_for_action(actor, action)
    if scope is ALL:
        return queryset
    if not scope:
        return queryset.none()
    return queryset.filter(**{f"{field}__in": scope})


def scope_by_visibility_or_action(actor, action, queryset, field="makerspace_id"):
    """Admit rows the actor can SEE, leaving 403-vs-404 to the permission check.

    Visible means local membership scope UNION the action's scope (including org
    grants). The handler still calls ``can`` afterwards and returns 403 from there.
    """
    scope = resolve_scope(actor)
    if scope is ALL:
        return queryset
    action_scope = makerspaces_for_action(actor, action)
    if action_scope is ALL:
        return queryset
    visible = scope | action_scope
    if not visible:
        return queryset.none()
    return queryset.filter(**{f"{field}__in": visible})


def effective_actions(actor, makerspace_id) -> set:
    """Return the membership-effective actions for an actor in one makerspace."""
    if actor is None or not getattr(actor, "is_authenticated", False):
        return set()
    if _id_in(makerspace_id, archived_makerspace_ids()):
        return set()
    # Organization grants never enter this superadmin branch: hidden-space authority
    # must continue to come only from an explicit makerspace membership.
    if actor.is_superuser or actor.role == User.Role.SUPERADMIN:
        if _id_in(makerspace_id, superadmin_hidden_makerspace_ids()):
            return actions_for_membership(_membership_for(actor, makerspace_id))
        return set(ROLE_GRANTABLE_ACTIONS)
    return actions_for_membership(
        _membership_for(actor, makerspace_id)
    ) | _org_actions_for(actor, makerspace_id)


def is_space_manager_identity(actor, makerspace_id) -> bool:
    """Return whether actor has the space-manager identity in this makerspace.

    This deliberately does not infer identity from actions: Machine Managers and
    custom roles granted manage_machines cannot configure types or pricing.
    """
    if actor is None or not getattr(actor, "is_authenticated", False):
        return False
    if _id_in(makerspace_id, archived_makerspace_ids()):
        return False
    membership = _membership_for(actor, makerspace_id)
    if actor.is_superuser or actor.role == User.Role.SUPERADMIN:
        if _id_in(makerspace_id, superadmin_hidden_makerspace_ids()):
            # In a hard-hidden makerspace a global superadmin is limited to their
            # explicit membership's role, so only a space-manager membership grants
            # the identity -- an Inventory/Machine Manager membership does not.
            return bool(membership and _membership_is_space_manager(membership))
        return True
    return bool(membership and _membership_is_space_manager(membership))


def is_handout_only(actor, makerspace_id) -> bool:
    """Whether the actor has a handover-only action bundle in one makerspace."""
    actions = effective_actions(actor, makerspace_id)
    return bool(actions) and actions <= HANDOUT_ACTIONS and bool(
        actions & _HANDOUT_MUTATIONS
    )


def can(actor, action, makerspace_id=None):
    """True if `actor` may perform `action` within `makerspace_id`.

    Superadmin: everything. Everyone else: authority is per-makerspace, so a
    makerspace_id is required and the membership role decides the allowed actions."""
    if actor is None or not getattr(actor, "is_authenticated", False):
        return False
    if makerspace_id is not None and _id_in(makerspace_id, archived_makerspace_ids()):
        return False
    # Organization grants never enter this superadmin branch: hidden-space authority
    # must continue to come only from an explicit makerspace membership.
    if actor.is_superuser or actor.role == User.Role.SUPERADMIN:
        if makerspace_id is None:
            return True
        if _id_in(makerspace_id, superadmin_hidden_makerspace_ids()):
            # Hard hide: global superpower is withheld for a hidden makerspace.
            # A superadmin who is an explicit member still gets that role's actions.
            return action in actions_for_membership(
                _membership_for(actor, makerspace_id)
            )
        return True
    if makerspace_id is None:
        return False
    if action in actions_for_membership(_membership_for(actor, makerspace_id)):
        return True
    return action in _org_actions_for(actor, makerspace_id)


def archived_makerspace_ids():
    """Compatibility name for every makerspace normal RBAC must exclude."""
    from apps.makerspaces.servability import unservable_makerspace_ids

    return unservable_makerspace_ids()


def _exclude_archived_ids(scope):
    archived = archived_makerspace_ids()
    return scope - archived if archived else scope


def _superadmin_visible_ids(actor, action=None):
    """Concrete ids a global superadmin may act in, or ALL when unrestricted."""
    excluded = _superadmin_hidden_to_exclude(actor, action) | archived_makerspace_ids()
    if not excluded:
        return ALL
    from apps.makerspaces.models import Makerspace

    return set(Makerspace.objects.exclude(id__in=excluded).values_list("id", flat=True))
