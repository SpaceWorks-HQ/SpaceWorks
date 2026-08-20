"""Shared authorization and response helpers for staff machine-service views."""

from django.db.models import Q
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse
from rest_framework import status
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from apps.accounts import rbac
from apps.admin_api.serializers_machine_service import MachineServiceRequestSerializer
from apps.hardware_requests.exceptions import ErrorSerializer
from apps.machines import role_scope
from apps.machines.models import MachineServiceRequest
from apps.makerspaces.guards import require_module
from apps.makerspaces.models import Makerspace


SERVICE_ERRORS = {
    400: OpenApiResponse(ErrorSerializer, description="Invalid service request input."),
    401: OpenApiResponse(description="Authentication required."),
    403: OpenApiResponse(description="Machine management permission required."),
    404: OpenApiResponse(description="Service request was not found."),
    409: OpenApiResponse(ErrorSerializer, description="Service workflow conflict."),
}
SERVICE_FILTERS = [
    OpenApiParameter("status", str, OpenApiParameter.QUERY),
    OpenApiParameter("machine", int, OpenApiParameter.QUERY),
    OpenApiParameter("bucket", int, OpenApiParameter.QUERY),
    OpenApiParameter("queue", int, OpenApiParameter.QUERY),
    OpenApiParameter("machine_type", str, OpenApiParameter.QUERY),
    OpenApiParameter("machine_type_id", int, OpenApiParameter.QUERY),
]


def _base_queryset():
    return MachineServiceRequest.objects.select_related(
        "makerspace",
        "bucket__machine__machine_type",
        "queue__machine_type",
        "assigned_machine__machine_type",
        "requester",
    ).prefetch_related("files", "consumptions")


def _visible_makerspace(actor, makerspace_id, action=rbac.Action.MANAGE_MACHINES):
    makerspace = get_object_or_404(
        rbac.scope_by_visibility_or_action(
            actor, action, Makerspace.objects.all(), field="id"
        ),
        pk=makerspace_id,
    )
    require_module(makerspace, "machine_service")
    if not rbac.can(actor, action, makerspace.pk):
        raise PermissionDenied()
    return makerspace


def _machine_partition_q(actor, makerspace_id):
    """The machine partition, or ``None`` for unrestricted machine authority.

    Exemption is resolved with ``role_scope.manage_scope_for``, NOT by asking whether
    ``makerspaces_for_action`` returned ``rbac.ALL``. Those two disagree for exactly one
    actor and it is the dangerous one: a global superadmin who also holds an explicit
    machine-scoped membership in a **hard-hidden** space is reduced to that role's
    authority by design, yet still answers ``ALL`` at the action level -- so the ALL
    shortcut handed them every row in the space and the role's machine links did nothing.
    ``manage_scopes_for`` already gives the right answer for both shapes (EXEMPT when a
    superadmin has no membership there, the role's links when they do), and using it is
    what keeps this partition consistent with the dashboard and every other surface.

    ``None`` rather than an empty ``Q()`` is load-bearing. Django's ``Q._combine``
    short-circuits a falsy operand -- ``Q() | Q(status=COMPLETED)`` returns
    ``Q(status=COMPLETED)``, not "everything OR completed" -- so an empty ``Q`` used as
    the identity for ``filter`` becomes an *annihilator* the moment the direct-collect arm
    is OR'd onto it. That inverted the union for every actor whose machine scope is
    unrestricted (a superadmin resolves to ``rbac.ALL``): instead of widening their view
    it narrowed it to COMPLETED rows only, hiding the entire live queue. Callers must
    therefore branch on ``None`` instead of relying on OR/AND identities.
    """
    scope = role_scope.manage_scope_for(actor, makerspace_id)
    if scope is role_scope.EXEMPT:
        return None
    return role_scope.scope_q_for(
        scope,
        machine_id_paths=role_scope.SERVICE_REQUEST_MACHINE_PATHS,
        type_id_paths=role_scope.SERVICE_REQUEST_TYPE_PATHS,
    )


def _manage_queryset(actor, makerspace_id):
    """Machine-scoped rows only, for lifecycle mutations and service files.

    ``makerspace_id`` is required: the partition is resolved per makerspace, and both
    callers reach this through ``_resolve_request``, which has already established which
    tenant the row belongs to.
    """
    queryset = rbac.scope_by_action(
        actor,
        rbac.Action.MANAGE_MACHINES,
        _base_queryset(),
        field="makerspace_id",
    ).filter(makerspace_id=makerspace_id)
    partition = _machine_partition_q(actor, makerspace_id)
    if partition is not None:
        queryset = queryset.filter(partition)
    return queryset.distinct()


def _read_or_collect_queryset(actor, makerspace_id):
    """Machine partition plus the cumulative direct-collect completed partition."""
    queryset = rbac.scope_by_action(
        actor,
        rbac.Action.COLLECT_SERVICE_REQUEST,
        _base_queryset(),
        field="makerspace_id",
    ).filter(makerspace_id=makerspace_id)
    visible = _machine_partition_q(actor, makerspace_id)
    if visible is None:
        # Unrestricted machine authority already covers every row in the tenant; the
        # direct-collect arm can only be a subset of it, so there is nothing to add.
        return queryset.distinct()
    if role_scope.role_grants_directly(
        actor, makerspace_id, rbac.Action.COLLECT_SERVICE_REQUEST
    ) or role_scope.organization_grants_directly(
        actor, makerspace_id, rbac.Action.COLLECT_SERVICE_REQUEST
    ):
        visible |= Q(status=MachineServiceRequest.Status.COMPLETED)
    return queryset.filter(visible).distinct()


def _resolve_request(actor, pk, *, action, queryset_builder):
    # Establish tenant visibility first: foreign/hidden rows stay a 404 while an actor
    # who can see the makerspace but lacks the requested action receives a 403.
    row = get_object_or_404(
        rbac.scope_by_visibility_or_action(
            actor,
            action,
            _base_queryset(),
            field="makerspace_id",
        ),
        pk=pk,
    )
    require_module(row.makerspace, "machine_service")
    if not rbac.can(actor, action, row.makerspace_id):
        raise PermissionDenied()
    return get_object_or_404(queryset_builder(actor, row.makerspace_id), pk=row.pk)


def _manageable_request(actor, pk):
    return _resolve_request(
        actor,
        pk,
        action=rbac.Action.MANAGE_MACHINES,
        queryset_builder=_manage_queryset,
    )


def _readable_or_collectable_request(actor, pk):
    return _resolve_request(
        actor,
        pk,
        action=rbac.Action.COLLECT_SERVICE_REQUEST,
        queryset_builder=_read_or_collect_queryset,
    )


def _query_int(request, name):
    value = request.query_params.get(name)
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError({name: "Must be an integer."}) from exc


def _response(row, code=status.HTTP_200_OK):
    row = _base_queryset().get(pk=row.pk)
    return Response(MachineServiceRequestSerializer(row).data, status=code)
