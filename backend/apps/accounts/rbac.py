"""Single source of truth for role permissions + makerspace scoping (PRD §4)."""
import logging

from django.db.models import F, Q

from apps.accounts.models import User
from apps.makerspaces.models import MakerspaceMembership

ALL = object()  # sentinel: unrestricted (superadmin)


def resolve_scope(actor):
    """Return the set of makerspace ids the actor may act in, or ALL."""
    if actor is None or not getattr(actor, "is_authenticated", False):
        return set()
    if actor.is_superuser or actor.role == User.Role.SUPERADMIN:
        return _superadmin_visible_ids(actor, None)
    # Organization grants confer actions, not identity, so they never widen this
    # action-agnostic scope (or scope_by_makerspace(), which derives from it).
    scope = set(actor.makerspace_memberships.filter(status="active").values_list("makerspace_id", flat=True))
    return _exclude_archived_ids(scope)


def scope_by_makerspace(actor, queryset, makerspace_field="makerspace_id"):
    """Filter a makerspace-owned queryset to the actor's scope (superadmin: unchanged)."""
    scope = resolve_scope(actor)
    if scope is ALL:
        return queryset
    if not scope:
        return queryset.none()
    return queryset.filter(**{f"{makerspace_field}__in": scope})


class Action:
    MANAGE_EVENTS = 'manage_events'
    MANAGE_BOOKINGS = 'manage_bookings'
    VIEW_INVENTORY = "view_inventory"
    EDIT_INVENTORY = "edit_inventory"
    ACCEPT_REQUEST = "accept_request"
    REJECT_REQUEST = "reject_request"
    ASSIGN_BOX = "assign_box"
    ISSUE_REQUEST = "issue_request"
    ISSUE_DIRECT_LOAN = "issue_direct_loan"  # create a handout with NO reviewed request
    RETURN_REQUEST = "return_request"
    UPLOAD_EVIDENCE = "upload_evidence"
    # Hand a finished machine-service job (a print, a laser cut) to its requester, and
    # nothing else about that job. Separate from MANAGE_MACHINES because collection is a
    # front-desk act while MANAGE_MACHINES is the whole machine lifecycle -- retiring a
    # printer, editing maintenance, reading usage. Requiring the latter to perform the
    # former is why a handover-only staffer previously could not hand over a print.
    COLLECT_SERVICE_REQUEST = "collect_service_request"
    MANAGE_QR = "manage_qr"
    MANAGE_PRINTING = "manage_printing"
    MANAGE_MACHINES = "manage_machines"
    VIEW_AUDIT = "view_audit"
    TRANSFER_STOCK = "transfer_stock"        # superadmin only
    MANAGE_STAFF = "manage_staff"            # superadmin only
    MANAGE_MAKERSPACE = "manage_makerspace"  # superadmin only


IMPLIED_ACTIONS = {
    # Collection is implied rather than granted, which is what makes this change carry no
    # migration and no regression: every Space Manager and Machine Manager already holds
    # MANAGE_MACHINES, so they keep collect authority without a single stored role
    # changing. Only a role that holds *neither* has to be given the narrow action.
    Action.MANAGE_MACHINES: {Action.MANAGE_PRINTING, Action.COLLECT_SERVICE_REQUEST},
}


def expand_implied_actions(actions) -> set:
    """Materialize the authority implied by an already-granted action set."""
    expanded = set(actions)
    pending = list(expanded)
    while pending:
        action = pending.pop()
        for implied in IMPLIED_ACTIONS.get(action, ()):
            if implied not in expanded:
                expanded.add(implied)
                pending.append(implied)
    return expanded


def actions_satisfying(requested_action) -> frozenset:
    """Return actions whose grant satisfies ``requested_action``.

    This is the reverse direction of ``expand_implied_actions`` for database
    filtering, where a JSON containment query can only inspect stored grants.
    """
    satisfying = {requested_action}
    pending = [requested_action]
    while pending:
        action = pending.pop()
        for grant, implied in IMPLIED_ACTIONS.items():
            if action in implied and grant not in satisfying:
                satisfying.add(grant)
                pending.append(grant)
    return frozenset(satisfying)


_SPACE_MANAGER_ACTIONS = {
    Action.VIEW_INVENTORY, Action.EDIT_INVENTORY, Action.ACCEPT_REQUEST,
    Action.REJECT_REQUEST, Action.ASSIGN_BOX, Action.ISSUE_REQUEST,
    Action.ISSUE_DIRECT_LOAN, Action.RETURN_REQUEST, Action.UPLOAD_EVIDENCE,
    Action.MANAGE_QR, Action.MANAGE_PRINTING, Action.VIEW_AUDIT,
    Action.MANAGE_MAKERSPACE, Action.MANAGE_MACHINES, Action.MANAGE_EVENTS,
    Action.MANAGE_BOOKINGS,
}
_PRINT_MANAGER_ACTIONS = {
    Action.MANAGE_PRINTING,
}
# Machine Manager: makerspace-wide machine authority. MANAGE_MACHINES alone unlocks the
# full machine lifecycle plus maintenance/warranty/usage/docs, which already gate on
# machine access — so no extra action is required (Part I).
_MACHINE_MANAGER_ACTIONS = {
    Action.MANAGE_MACHINES,
}
_INVENTORY_MANAGER_ACTIONS = {
    Action.VIEW_INVENTORY, Action.EDIT_INVENTORY, Action.ACCEPT_REQUEST,
    Action.REJECT_REQUEST, Action.ASSIGN_BOX, Action.ISSUE_REQUEST,
    Action.ISSUE_DIRECT_LOAN, Action.RETURN_REQUEST, Action.UPLOAD_EVIDENCE,
    Action.MANAGE_QR, Action.VIEW_AUDIT,
}
# Authority for non-superadmins is keyed on the PER-MAKERSPACE membership role,
# NOT the global User.role (review fix #3). A user who is globally `space_manager` but only
# an inventory_manager member of makerspace B gets only inventory_manager actions in B.
_MEMBERSHIP_ROLE_ACTIONS = {
    MakerspaceMembership.Role.SPACE_MANAGER: _SPACE_MANAGER_ACTIONS,
    MakerspaceMembership.Role.INVENTORY_MANAGER: _INVENTORY_MANAGER_ACTIONS,
    # Kept as the raw legacy value so an unmigrated/null-FK membership remains
    # session-compatible after the protected default is retired.
    "print_manager": _PRINT_MANAGER_ACTIONS,
    MakerspaceMembership.Role.MACHINE_MANAGER: _MACHINE_MANAGER_ACTIONS,
}


ALL_ACTIONS = frozenset(
    value
    for name, value in vars(Action).items()
    if name.isupper() and isinstance(value, str)
)
ROLE_FORBIDDEN_ACTIONS = frozenset({
    Action.TRANSFER_STOCK,
    Action.MANAGE_STAFF,
})
ROLE_GRANTABLE_ACTIONS = frozenset(ALL_ACTIONS - ROLE_FORBIDDEN_ACTIONS)
ROLE_SUPERADMIN_ASSIGNABLE_ACTIONS = frozenset({Action.MANAGE_MAKERSPACE})
# What counts as handover-only work: taking an accepted request or a finished machine job
# to the counter, handing it over, taking it back, and photographing both ends of that.
#
# This is a DESCRIPTION, not a grant and no longer a ceiling. It is derived from no role --
# the built-in that used to define it was retired, and `role_services._validate_actions`
# dropped the cap that keyed on it, so any role may hold any subset of these alongside
# anything else. Its only consumer is `is_handout_only`, which decides how narrow the staff
# console renders for someone whose whole job is the front desk. Adding an action here
# widens what still reads as "front desk"; it grants nothing to anyone.
HANDOUT_ACTIONS = frozenset({
    Action.VIEW_INVENTORY, Action.ASSIGN_BOX, Action.ISSUE_REQUEST,
    Action.ISSUE_DIRECT_LOAN, Action.RETURN_REQUEST, Action.UPLOAD_EVIDENCE,
    Action.COLLECT_SERVICE_REQUEST,
})
_HANDOUT_MUTATIONS = frozenset(HANDOUT_ACTIONS - {Action.VIEW_INVENTORY})


def actions_for_membership(membership) -> set:
    """Resolve role actions for a membership, failing closed on invalid role data."""
    if membership is None or getattr(membership, "status", "active") != "active":
        return set()
    if membership.assigned_role_id is not None:
        role = membership.assigned_role
        if role.makerspace_id != membership.makerspace_id:
            return set()
        value = role.granted_actions
        if not isinstance(value, list):
            logging.getLogger(__name__).warning(
                "Ignoring malformed granted actions on an assigned makerspace role."
            )
            return set()
        return expand_implied_actions({
            action
            for action in value
            if isinstance(action, str) and action in ROLE_GRANTABLE_ACTIONS
        })
    return expand_implied_actions(_MEMBERSHIP_ROLE_ACTIONS.get(membership.role, set()))


def actions_for_organization_membership(membership) -> set:
    """Resolve one organization grant with the same fail-closed action rules."""
    if (
        membership is None
        or getattr(membership, "status", "active") != "active"
        or not getattr(getattr(membership, "organization", None), "is_active", False)
    ):
        return set()
    value = membership.granted_actions
    if not isinstance(value, list):
        logging.getLogger(__name__).warning(
            "Ignoring malformed granted actions on an organization membership."
        )
        return set()
    return expand_implied_actions({
        action
        for action in value
        if isinstance(action, str) and action in ROLE_GRANTABLE_ACTIONS
    })


def _organization_authority_memberships(actor, *, makerspace_ids=None):
    """Active organization grants whose linked makerspace may serve traffic."""
    from apps.makerspaces.servability import servable_q
    from apps.organizations.models import OrganizationMembership

    filters = (
        Q(
            user=actor,
            status=OrganizationMembership.Status.ACTIVE,
            organization__is_active=True,
            organization__makerspace_links__makerspace__superadmin_access_enabled=True,
        )
        & servable_q("organization__makerspace_links__makerspace")
    )
    if makerspace_ids is not None:
        filters &= Q(
            organization__makerspace_links__makerspace_id__in=makerspace_ids
        )
    return OrganizationMembership.objects.filter(filters)


def has_any_org_authority(actor) -> bool:
    """Return whether one indexed query finds any usable organization grant."""
    if actor is None or not getattr(actor, "is_authenticated", False):
        return False
    granted_filter = Q()
    for action in ROLE_GRANTABLE_ACTIONS:
        granted_filter |= Q(granted_actions__contains=[action])
    return _organization_authority_memberships(actor).filter(
        granted_filter
    ).exists()


def _org_actions_for(actor, makerspace_id) -> set:
    """Return actions active organization grants confer in one makerspace.

    Hard-hidden makerspaces are excluded here, not at the call sites, so every
    consumer of organization authority inherits the exclusion. Reason: an
    OrganizationMembership has no makerspace FK, so it sits in
    `GLOBAL_ADMIN_MODELS` and the admin hide-scoping never narrows it. Without
    this a superadmin could use the global membership admin to grant a third
    party authority inside a makerspace that is hard-hidden FROM that superadmin
    -- a proxy around the hide invariant. A real local MakerspaceMembership in a
    hidden space still confers authority; an organization grant never does.
    """
    if actor is None or not getattr(actor, "is_authenticated", False):
        return set()
    granted = set()
    memberships = _organization_authority_memberships(
        actor, makerspace_ids=[makerspace_id]
    ).select_related("organization")
    for membership in memberships:
        granted.update(actions_for_organization_membership(membership))
    return granted


def _org_scope_for_action(actor, action) -> set:
    """Return makerspace ids where an active organization grant satisfies action."""
    if actor is None or not getattr(actor, "is_authenticated", False):
        return set()
    satisfying = actions_satisfying(action) & ROLE_GRANTABLE_ACTIONS
    if not satisfying:
        return set()
    granted_filter = Q()
    for granted_action in satisfying:
        granted_filter |= Q(granted_actions__contains=[granted_action])
    rows = (
        _organization_authority_memberships(actor)
        .filter(granted_filter)
        .values_list(
            "granted_actions",
            "organization__makerspace_links__makerspace_id",
        )
    )
    scope = set()
    for value, makerspace_id in rows:
        if not isinstance(value, list):
            logging.getLogger(__name__).warning(
                "Ignoring malformed granted actions on an organization membership."
            )
            continue
        expanded = expand_implied_actions({
            granted_action
            for granted_action in value
            if (
                isinstance(granted_action, str)
                and granted_action in ROLE_GRANTABLE_ACTIONS
            )
        })
        if action in expanded:
            scope.add(makerspace_id)
    return scope


def _action_scope_filters(action):
    """Build assigned-role and legacy-role filters for an action scope query."""
    satisfying = actions_satisfying(action)
    assigned_filter = Q()
    for granted_action in satisfying:
        assigned_filter |= Q(assigned_role__granted_actions__contains=[granted_action])
    legacy_roles = [
        role
        for role, actions in _MEMBERSHIP_ROLE_ACTIONS.items()
        if actions & satisfying
    ]
    return assigned_filter, legacy_roles


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

    This repo deliberately distinguishes two denials: a makerspace you are not in at all
    returns 404 (the object is invisible), while a makerspace you ARE in but lack the
    action for returns 403. Prefiltering an action-gated handler with `scope_by_action`
    alone collapses the second into the first, so a member of the space who lacks the
    action starts getting 404 -- which is what `test_visible_underprivileged_roles_get_403`
    pins. Prefiltering with membership scope alone excludes organization-derived
    authority, which is the whole point of the org branch.

    So: visible = local membership scope UNION the action's scope (which includes org
    grants). The handler still calls `can(...)` afterwards and returns 403 from there.
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


def membership_role(actor, makerspace_id):
    """Return the actor's MakerspaceMembership.role for this makerspace, or None."""
    membership = actor.makerspace_memberships.filter(
        status="active",
        makerspace_id=makerspace_id
    ).first()
    return membership.role if membership else None


def _membership_for(actor, makerspace_id) -> MakerspaceMembership | None:
    return actor.makerspace_memberships.select_related("assigned_role").filter(
        status="active",
        makerspace_id=makerspace_id
    ).first()


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
            # the identity — an Inventory/Machine Manager membership does not.
            return bool(membership and _membership_is_space_manager(membership))
        return True
    return bool(membership and _membership_is_space_manager(membership))


def _membership_is_space_manager(membership) -> bool:
    if membership.assigned_role_id is not None:
        role = membership.assigned_role
        return bool(role and role.makerspace_id == membership.makerspace_id and role.legacy_role == "space_manager")
    return membership.role == MakerspaceMembership.Role.SPACE_MANAGER


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


def superadmin_hidden_makerspace_ids():
    from apps.makerspaces.models import Makerspace

    return set(
        Makerspace.objects.filter(
            superadmin_access_enabled=False,
        )
        .values_list("id", flat=True)
    )


def archived_makerspace_ids():
    """Compatibility name for every makerspace normal RBAC must exclude."""
    from apps.makerspaces.servability import unservable_makerspace_ids

    return unservable_makerspace_ids()


def _exclude_archived_ids(scope):
    archived = archived_makerspace_ids()
    return scope - archived if archived else scope


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
    when given) — a superadmin who is also a real member keeps that membership's
    role-scoped access, but never global superpower (review fix #2)."""
    hidden = superadmin_hidden_makerspace_ids()
    if not hidden:
        return set()
    memberships = actor.makerspace_memberships.filter(makerspace_id__in=hidden, status="active")
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


def _superadmin_visible_ids(actor, action=None):
    """Concrete id set a global superadmin may act in (all makerspaces minus the
    hard-hidden, non-member ones and archived ones). Returns ALL when there is
    no exclusion so the fast path is preserved for the common case."""
    excluded = _superadmin_hidden_to_exclude(actor, action) | archived_makerspace_ids()
    if not excluded:
        return ALL
    from apps.makerspaces.models import Makerspace

    return set(Makerspace.objects.exclude(id__in=excluded).values_list("id", flat=True))


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
