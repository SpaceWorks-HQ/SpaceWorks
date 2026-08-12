"""Resolve which machines a role's ``MANAGE_MACHINES`` grant reaches.

This narrows **tier 1 only** (see ``access.py``). The other two tiers are already scoped
by construction and are deliberately left alone: a type manager is bounded by
``MachineType.managing_action``, and a per-machine operator is bounded by the row that
names the machine. Re-scoping either through this module would double-filter authority
that was already narrow, and would break a lab that runs entirely on operator rows.

Everything here is derived from the actor's **membership role row** in one makerspace,
so it composes with rather than replaces ``rbac``: a caller establishes that
``MANAGE_MACHINES`` is granted at all (which is where hard-hide and archived scoping are
enforced), then asks this module which machines that grant reaches.

Two shapes of answer, and the sentinel matters:

``EXEMPT``
    Scoping does not apply -- the actor reaches every machine in the makerspace,
    including types created later. Returned for a superadmin, for a role holding
    ``MANAGE_MAKERSPACE``, and for a membership whose ``assigned_role`` is null.

``(type_ids, machine_ids)``
    The union of linked types and linked machines. **Both empty means no machines**, the
    fail-closed default that gives the mechanism its value.
"""

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
    as the per-actor path — it is the same `_scope_for_membership` underneath, so the two
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


def grants_directly(actor, makerspace_id, action):
    """Whether the actor's role grants ``action`` outright, rather than by implication.

    This exists because ``IMPLIED_ACTIONS`` would otherwise punch a hole straight through
    machine scoping. ``MANAGE_MACHINES`` implies ``MANAGE_PRINTING``, and the built-in
    ``3d_printer`` type carries ``managing_action="manage_printing"`` -- so a role scoped
    to lasers alone still satisfied the tier-2 type-manager check for every 3D printer in
    the lab, and the narrowing it was given did nothing for the largest fleet most
    makerspaces own.

    The fix is to read tier 2 off the **stored** grant. A role that really is a Print
    Manager holds ``manage_printing`` directly and keeps its unscoped type authority; a
    role that only holds ``MANAGE_MACHINES`` gets its printer authority through tier 1,
    where the links apply. The implication itself is untouched -- ``rbac.can`` still
    answers yes, so nothing outside this module changes.
    """
    if actor is None or not getattr(actor, "is_authenticated", False):
        return False
    if rbac._is_superadmin(actor):
        # Authority does not come from a role row, so no role can qualify it. Tier 1
        # already treats them as EXEMPT; agreeing here keeps the two consistent.
        return not rbac.superadmin_hidden_block_applies(actor, makerspace_id, action)
    return role_grants_directly(actor, makerspace_id, action)


def role_grants_directly(actor, makerspace_id, action):
    """Whether the actor's assigned ROLE stores ``action`` outright.

    Deliberately blind to superadmin status, which is the whole difference from
    :func:`grants_directly`. That function short-circuits on ``_is_superadmin`` before it
    ever reads a role, which is right for tier-2 type authority (it does not come from a
    role row) and wrong for any caller asking "did this role grant this?".

    The machine-service read partition needs the second form. A global superadmin who is
    ALSO given an explicit machine-scoped membership in a hard-hidden space is reduced to
    that role's actions by design, and holds ``COLLECT_SERVICE_REQUEST`` only by
    implication from ``MANAGE_MACHINES``; asking ``grants_directly`` there answers yes and
    hands them the makerspace-wide completed partition their machine links exist to deny.
    """
    if actor is None or not getattr(actor, "is_authenticated", False):
        return False
    membership = actor.makerspace_memberships.select_related("assigned_role").filter(
        status="active", makerspace_id=makerspace_id
    ).first()
    if membership is None:
        return False
    if membership.assigned_role_id is None:
        return action in rbac._MEMBERSHIP_ROLE_ACTIONS.get(membership.role, ())
    role = membership.assigned_role
    if role.makerspace_id != membership.makerspace_id:
        return False
    granted = role.granted_actions if isinstance(role.granted_actions, list) else []
    return action in granted


def makerspaces_granting_directly(actor, action):
    """Query-level twin of :func:`grants_directly`: ids, or ``rbac.ALL``.

    ``rbac.makerspaces_for_action`` deliberately expands implied grants (a JSON
    containment query cannot follow implications any other way), which is right for every
    other caller and wrong for the tier-2 branch of machine scoping — for the same reason
    :func:`grants_directly` exists. Keeping the two in step matters: the object check and
    the list filter disagreeing is how a row becomes visible in a list and 403s on click.
    """
    if actor is None or not getattr(actor, "is_authenticated", False):
        return set()
    if rbac._is_superadmin(actor):
        return rbac.makerspaces_for_action(actor, action)
    legacy_roles = [
        role
        for role, actions in rbac._MEMBERSHIP_ROLE_ACTIONS.items()
        if action in actions
    ]
    memberships = actor.makerspace_memberships.filter(status="active")
    scope = set(
        memberships.filter(
            assigned_role__isnull=False,
            assigned_role__granted_actions__contains=[action],
        ).values_list("makerspace_id", flat=True)
    )
    if legacy_roles:
        scope |= set(
            memberships.filter(
                assigned_role__isnull=True, role__in=legacy_roles
            ).values_list("makerspace_id", flat=True)
        )
    return rbac._exclude_archived_ids(scope)


def grant_builtin_type_scope(role):
    """Link a freshly seeded role to every built-in machine type.

    The seeded Machine Manager default would otherwise be born inert: it grants
    ``MANAGE_MACHINES``, scoping fails closed, and nothing links it -- so every newly
    created makerspace would ship a protected default role that can touch no machine and
    a Machines tab that does not appear. Migration `0020` gave existing roles exactly
    these links; this is the same grant for roles created after it, and without it a
    makerspace created the day after the upgrade would behave differently from one
    created the day before.

    Only built-ins, because a brand-new makerspace has no custom types yet. Idempotent,
    and a no-op for a role that does not grant ``MANAGE_MACHINES`` or that is exempt
    anyway.
    """
    from .models import MachineType

    granted = role.granted_actions if isinstance(role.granted_actions, list) else []
    granted = {action for action in granted if isinstance(action, str)}
    if Action.MANAGE_MACHINES not in granted or Action.MANAGE_MAKERSPACE in granted:
        return
    RoleMachineTypeScope.objects.bulk_create(
        [
            RoleMachineTypeScope(role=role, machine_type_id=type_id)
            for type_id in MachineType.objects.filter(
                makerspace__isnull=True
            ).values_list("id", flat=True)
        ],
        ignore_conflicts=True,
    )


def scope_q_for(scope, *, machine_id_paths=(), type_id_paths=()):
    """A pure ``Q`` for an already-resolved scope, with **no** makerspace clause.

    For callers that have already constrained the tenant themselves — the report builders,
    which are handed one makerspace id (or none, for the superadmin aggregate) before they
    start. ``EXEMPT`` becomes an empty ``Q()``, which is the identity for ``filter``, so a
    space manager's report is byte-for-byte the query it was before this existed.
    """
    from django.db.models import Q

    if scope is EXEMPT:
        return Q()
    type_ids, machine_ids = scope
    if not type_ids and not machine_ids:
        return Q(pk__in=[])
    q = Q(pk__in=[])
    if machine_ids:
        for path in machine_id_paths:
            q |= Q(**{f"{path}__in": machine_ids})
    if type_ids:
        for path in type_id_paths:
            q |= Q(**{f"{path}__in": type_ids})
    return q


def scoped_related_q(
    actor,
    makerspace_ids,
    *,
    machine_id_paths=(),
    type_id_paths=(),
    makerspace_field="makerspace_id",
):
    """A ``Q`` narrowing rows that hang off a machine to the actor's role scope.

    The makerspace-level surfaces (the service queue, consumable pools, payments,
    reconciliation, reports) were all gated on ``MANAGE_MACHINES`` alone, which meant a
    role scoped to the laser cutters still read every printer job in the lab, its costs
    and its requesters' names. Each one now ANDs this in.

    Callers pass the lookup paths explicitly rather than having them derived, because the
    route from a row to a machine is genuinely per-model and often plural -- a service
    request reaches one through ``assigned_machine`` (null until allocated), through its
    bucket, and through its queue's machine **type**. Naming them at the call site is what
    makes a missed path reviewable.

    A row that reaches no machine at all matches nothing for a scoped role. That is the
    fail-closed direction and it is intended: an unallocated request nobody's scope covers
    should be invisible rather than universally visible.
    """
    from django.db.models import Q

    q = Q(pk__in=[])
    for ms_id, scope in manage_scopes_for(actor, makerspace_ids).items():
        tenant = Q(**{makerspace_field: ms_id})
        if scope is EXEMPT:
            q |= tenant
            continue
        type_ids, machine_ids = scope
        if not type_ids and not machine_ids:
            continue
        inner = Q(pk__in=[])
        if machine_ids:
            for path in machine_id_paths:
                inner |= Q(**{f"{path}__in": machine_ids})
        if type_ids:
            for path in type_id_paths:
                inner |= Q(**{f"{path}__in": type_ids})
        q |= tenant & inner
    return q


# Every route from a machine-service request to a machine. `assigned_machine` is null
# until the request is allocated, which is exactly when the queue's type is the only
# thing that says who owns the job -- so the type paths are not a convenience, they are
# what keeps a pending request visible to the team that will run it.
SERVICE_REQUEST_MACHINE_PATHS = ("assigned_machine_id", "bucket__machine_id")
SERVICE_REQUEST_TYPE_PATHS = (
    "assigned_machine__machine_type_id",
    "bucket__machine__machine_type_id",
    "queue__machine_type_id",
)


def scoped_service_requests(actor, queryset, makerspace_ids):
    """Narrow a MachineServiceRequest queryset to the actor's role scope."""
    return queryset.filter(
        scoped_related_q(
            actor,
            makerspace_ids,
            machine_id_paths=SERVICE_REQUEST_MACHINE_PATHS,
            type_id_paths=SERVICE_REQUEST_TYPE_PATHS,
        )
    ).distinct()


def covers_service_request(actor, service_request):
    """Object-level twin of :func:`scoped_service_requests`.

    Kept as a queryset filter rather than a pure predicate so the two can never drift on
    the paths they consider -- a detail view allowing what the list hides is the failure
    mode this phase exists to prevent.
    """
    from .models_service import MachineServiceRequest

    return scoped_service_requests(
        actor,
        MachineServiceRequest.objects.filter(pk=service_request.pk),
        [service_request.makerspace_id],
    ).exists()


def scoped_q(actor, makerspace_ids):
    """A ``Q`` selecting the machines the actor's role scope reaches, at query level.

    Returns a never-matching ``Q`` when the scope is empty everywhere, so a caller can
    OR this into a wider filter without special-casing.
    """
    from django.db.models import Q

    q = Q(pk__in=[])
    for ms_id, scope in manage_scopes_for(actor, makerspace_ids).items():
        if scope is EXEMPT:
            q |= Q(makerspace_id=ms_id)
            continue
        type_ids, machine_ids = scope
        if not type_ids and not machine_ids:
            continue
        covered = Q(pk__in=machine_ids) if machine_ids else Q(pk__in=[])
        if type_ids:
            covered |= Q(machine_type_id__in=type_ids)
        # AND the makerspace so a link that should never have been written across tenants
        # is inert rather than a leak.
        q |= Q(makerspace_id=ms_id) & covered
    return q
