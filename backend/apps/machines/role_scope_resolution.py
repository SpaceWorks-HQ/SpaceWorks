"""Resolve role-linked machine scopes and test their coverage."""

from collections import defaultdict

from apps.accounts import rbac
from apps.accounts.rbac import Action

from .models_role_scope import RoleMachineScope, RoleMachineTypeScope


# Scoping does not restrict this actor here. A distinct object rather than None/True so a
# caller cannot confuse "unrestricted" with "restricted to nothing" -- the two are
# opposites and both are falsy in the shapes we would otherwise reach for.
EXEMPT = object()

# The fail-closed answer: a role that holds MANAGE_MACHINES but has no links.
NOTHING = (frozenset(), frozenset())


def _scope_for_membership(membership):
    """EXEMPT, a role id to look links up for, or NOTHING. No queries beyond the FK."""
    if membership.assigned_role_id is None:
        # The frozen legacy fallback (`rbac._MEMBERSHIP_ROLE_ACTIONS`) is not a role row,
        # so there is nothing to hang links on. Scoping it would silently strip a legacy
        # Machine Manager of every machine at upgrade time, which is precisely the
        # regression the backfill exists to prevent.
        return EXEMPT, None
    role = membership.assigned_role
    if role.makerspace_id != membership.makerspace_id:
        # Same tenant-mismatch fail-closed rule as `rbac.actions_for_membership`.
        return NOTHING, None
    granted = role.granted_actions if isinstance(role.granted_actions, list) else []
    if Action.MANAGE_MAKERSPACE in rbac.expand_implied_actions(
        action for action in granted if isinstance(action, str)
    ):
        # Locked decision: a space manager always covers every machine, including types
        # that do not exist yet. Making them enumerate types to keep administering their
        # own lab is a worse failure than the broad grant this mechanism narrows.
        return EXEMPT, None
    return None, role.pk


def manage_scopes_for(actor, makerspace_ids):
    """Map each makerspace id to EXEMPT or ``(type_ids, machine_ids)``.

    Two queries regardless of how many makerspaces are asked about, because the callers
    that matter are list endpoints -- resolving this per row would put an N+1 behind
    every machine list in the console.

    A makerspace with no membership row resolves to EXEMPT for a superadmin (their grant
    does not come from a role, so no role can scope it) and to NOTHING otherwise. The
    latter is unreachable through the normal callers, which only ask about makerspaces
    where ``MANAGE_MACHINES`` is already granted, but it is the safe answer if it ever is.
    """
    ids = {ms_id for ms_id in makerspace_ids if ms_id is not None}
    ids -= rbac.archived_makerspace_ids()
    if not ids or actor is None or not getattr(actor, "is_authenticated", False):
        return {}

    resolved = {}
    role_to_makerspace = {}
    memberships = actor.makerspace_memberships.select_related("assigned_role").filter(
        status="active", makerspace_id__in=ids
    )
    for membership in memberships:
        answer, role_id = _scope_for_membership(membership)
        if answer is not None:
            resolved[membership.makerspace_id] = answer
        else:
            role_to_makerspace[role_id] = membership.makerspace_id

    if role_to_makerspace:
        role_ids = list(role_to_makerspace)
        types = defaultdict(set)
        machines = defaultdict(set)
        for role_id, type_id in RoleMachineTypeScope.objects.filter(
            role_id__in=role_ids
        ).values_list("role_id", "machine_type_id"):
            types[role_id].add(type_id)
        for role_id, machine_id in RoleMachineScope.objects.filter(
            role_id__in=role_ids
        ).values_list("role_id", "machine_id"):
            machines[role_id].add(machine_id)
        for role_id, ms_id in role_to_makerspace.items():
            resolved[ms_id] = (
                frozenset(types[role_id]),
                frozenset(machines[role_id]),
            )

    superadmin = rbac._is_superadmin(actor)
    for ms_id in ids - set(resolved):
        resolved[ms_id] = EXEMPT if superadmin else NOTHING
    return resolved


def manage_scope_for(actor, makerspace_id):
    """Single-makerspace form of :func:`manage_scopes_for`."""
    return manage_scopes_for(actor, [makerspace_id]).get(makerspace_id, NOTHING)


def manage_scopes_for_memberships(memberships):
    """Map membership id -> EXEMPT or ``(type_ids, machine_ids)``.

    The membership-keyed twin of :func:`manage_scopes_for`, for callers that already hold
    the rows and would otherwise resolve one actor at a time. Notification recipient
    resolution is exactly that shape: it has already selected the memberships and needs
    each one's machine reach, so a per-actor call would put an N+1 behind every alert.

    Two link queries regardless of how many memberships are passed, and the same answers
    as the per-actor path -- it is the same `_scope_for_membership` underneath, so the two
    cannot drift.
    """
    memberships = list(memberships)
    resolved = {}
    role_to_memberships = defaultdict(list)
    for membership in memberships:
        answer, role_id = _scope_for_membership(membership)
        if answer is not None:
            resolved[membership.pk] = answer
        else:
            role_to_memberships[role_id].append(membership.pk)

    if role_to_memberships:
        role_ids = list(role_to_memberships)
        types = defaultdict(set)
        machines = defaultdict(set)
        for role_id, type_id in RoleMachineTypeScope.objects.filter(
            role_id__in=role_ids
        ).values_list("role_id", "machine_type_id"):
            types[role_id].add(type_id)
        for role_id, machine_id in RoleMachineScope.objects.filter(
            role_id__in=role_ids
        ).values_list("role_id", "machine_id"):
            machines[role_id].add(machine_id)
        for role_id, membership_ids in role_to_memberships.items():
            scope = (frozenset(types[role_id]), frozenset(machines[role_id]))
            for membership_id in membership_ids:
                resolved[membership_id] = scope
    return resolved


def scope_covers_machine(scope, machine):
    """Whether a resolved scope reaches one machine. Pure -- no queries."""
    if scope is EXEMPT:
        return True
    type_ids, machine_ids = scope
    return machine.pk in machine_ids or machine.machine_type_id in type_ids


def scope_covers_type(scope, machine_type):
    """Whether a resolved scope reaches a whole type.

    Used for creation, where there is no machine yet to check. A per-machine link cannot
    answer this -- it names a machine that does not exist -- so only a type link grants
    the right to add a machine of that type.
    """
    if scope is EXEMPT:
        return True
    if machine_type is None:
        return False
    type_ids, _ = scope
    type_id = getattr(machine_type, "pk", machine_type)
    return type_id in type_ids


def covers_machine(actor, machine):
    """Whether the actor's role scope reaches this machine. Assumes the grant is held."""
    return scope_covers_machine(manage_scope_for(actor, machine.makerspace_id), machine)


def covers_type(actor, makerspace_id, machine_type):
    """Whether the actor's role scope reaches this type. Assumes the grant is held."""
    return scope_covers_type(manage_scope_for(actor, makerspace_id), machine_type)
