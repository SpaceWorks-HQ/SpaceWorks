"""RBAC action vocabulary and role-to-action resolution."""

import logging

from django.db.models import Q

from apps.makerspaces.models import MakerspaceMembership


ALL = object()  # sentinel: unrestricted (superadmin)


class Action:
    MANAGE_EVENTS = "manage_events"
    MANAGE_BOOKINGS = "manage_bookings"
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
# machine access -- so no extra action is required (Part I).
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
ORGANIZATION_GRANTABLE_ACTIONS = frozenset(
    ROLE_GRANTABLE_ACTIONS - {Action.MANAGE_MACHINES}
)
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
            logging.getLogger("apps.accounts.rbac").warning(
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
        logging.getLogger("apps.accounts.rbac").warning(
            "Ignoring malformed granted actions on an organization membership."
        )
        return set()
    return expand_implied_actions({
        action
        for action in value
        if isinstance(action, str)
        and action in ORGANIZATION_GRANTABLE_ACTIONS
    })


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
