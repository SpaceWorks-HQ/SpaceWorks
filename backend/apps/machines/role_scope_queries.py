"""Query filters built from resolved machine-role scopes."""

from django.db.models import Q

from .role_scope_resolution import EXEMPT, manage_scopes_for


def scope_q_for(scope, *, machine_id_paths=(), type_id_paths=()):
    """A pure ``Q`` for an already-resolved scope, with no makerspace clause."""
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

    Callers name every machine/type lookup path explicitly. A row reaching no machine
    matches nothing for a scoped role, preserving the fail-closed behavior.
    """
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
# thing that says who owns the job.
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
    """Object-level twin of :func:`scoped_service_requests`."""
    from .models_service import MachineServiceRequest

    return scoped_service_requests(
        actor,
        MachineServiceRequest.objects.filter(pk=service_request.pk),
        [service_request.makerspace_id],
    ).exists()


def scoped_q(actor, makerspace_ids):
    """A ``Q`` selecting the machines the actor's role scope reaches."""
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
