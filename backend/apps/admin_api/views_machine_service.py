"""Staff queue endpoints for generic machine service requests."""

from django.db.models import Q
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import rbac
from apps.accounts.models import User
from apps.admin_api.permissions import IsActiveStaff
from apps.admin_api.serializers_machine_service import (
    EmptyServiceActionSerializer, MachineServiceRequestSerializer,
    MachineServiceSubmitSerializer, ServiceAcceptSerializer, ServiceCompleteSerializer,
    ServiceFailSerializer, ServiceRejectSerializer, ServiceStartSerializer,
)
from apps.hardware_requests.exceptions import ErrorSerializer
from apps.machines import role_scope, service_workflow
from apps.machines.models import Machine, MachineServiceRequest
from apps.makerspaces.guards import require_module
from apps.makerspaces.models import Makerspace, MakerspaceMembership
from apps.payments.models import Payment


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
]


def _visible_makerspace(actor, makerspace_id, action=rbac.Action.MANAGE_MACHINES):
    makerspace = get_object_or_404(
        rbac.scope_by_makerspace(actor, Makerspace.objects.all(), makerspace_field="id"),
        pk=makerspace_id,
    )
    require_module(makerspace, "machine_service")
    if not rbac.can(actor, action, makerspace.pk):
        raise PermissionDenied()
    return makerspace


def _collect_only(actor, makerspace_id):
    """Holds the narrow collect action but not machine management.

    The distinction drives what such an actor may *see*, not only what they may do: a
    front-desk handover role has no business reading the queue, draft requests or jobs
    still on a machine, so its view is narrowed to the ones actually awaiting collection.
    A MANAGE_MACHINES holder is never collect-only, because the implication makes them
    hold both.
    """
    return (
        rbac.can(actor, rbac.Action.COLLECT_SERVICE_REQUEST, makerspace_id)
        and not rbac.can(actor, rbac.Action.MANAGE_MACHINES, makerspace_id)
    )


def _request_queryset(actor, makerspace_id=None):
    queryset = MachineServiceRequest.objects.select_related(
        "makerspace", "bucket__machine__machine_type", "queue__machine_type", "assigned_machine__machine_type", "requester"
    ).prefetch_related("files", "consumptions")
    # Scoped on the narrow action, not MANAGE_MACHINES: `actions_satisfying` maps it back
    # to MANAGE_MACHINES as well, so a manager's scope is unchanged while a collect-only
    # role gains exactly its own makerspaces.
    queryset = rbac.scope_by_action(actor, rbac.Action.COLLECT_SERVICE_REQUEST, queryset,
                                    field="makerspace_id")
    queryset = _narrow_to_machine_scope(actor, queryset)
    if makerspace_id is not None and _collect_only(actor, makerspace_id):
        return queryset.filter(status=MachineServiceRequest.Status.COMPLETED)
    return queryset


def _narrow_to_machine_scope(actor, queryset):
    """Cut the queue down to the jobs the actor's role is actually scoped to run.

    `MANAGE_MACHINES` was makerspace-wide here, so a role scoped to the laser cutters
    still read every printer job in the lab — its costs, its notes and its requester's
    contact details. Only the MANAGE_MACHINES-derived part of the scope is narrowed:
    a **collect-only** front-desk role holds a different action entirely, and machine
    scoping has nothing to say about it, so its makerspaces are added back untouched.
    """
    manage_scope = rbac.makerspaces_for_action(actor, rbac.Action.MANAGE_MACHINES)
    if manage_scope is rbac.ALL:
        return queryset
    collect_scope = rbac.makerspaces_for_action(actor, rbac.Action.COLLECT_SERVICE_REQUEST)
    collect_only = (
        set() if collect_scope is rbac.ALL else set(collect_scope) - set(manage_scope)
    )
    scoped = role_scope.scoped_related_q(
        actor,
        manage_scope,
        machine_id_paths=role_scope.SERVICE_REQUEST_MACHINE_PATHS,
        type_id_paths=role_scope.SERVICE_REQUEST_TYPE_PATHS,
    )
    if collect_only:
        scoped |= Q(makerspace_id__in=collect_only)
    return queryset.filter(scoped).distinct()


def _manageable_request(actor, pk, action=rbac.Action.MANAGE_MACHINES):
    # Tenant visibility is established before the action check, so foreign/hidden
    # rows remain a 404 while an in-space but unauthorized actor receives a 403.
    #
    # `action` is MANAGE_MACHINES for every operation that changes what a machine did --
    # accept, start, complete, fail, reprint. Only collection passes the narrow action,
    # which is the whole point: handing a finished job to its owner is a front-desk act,
    # while the rest of this API is the machine lifecycle.
    row = get_object_or_404(
        rbac.scope_by_makerspace(
            actor,
            MachineServiceRequest.objects.select_related(
                "makerspace", "bucket__machine__makerspace", "bucket__machine__machine_type", "queue__machine_type", "assigned_machine__machine_type", "requester"
            ).prefetch_related("files", "consumptions"),
            makerspace_field="makerspace_id",
        ), pk=pk,
    )
    require_module(row.makerspace, "machine_service")
    if not rbac.can(actor, action, row.makerspace_id):
        raise PermissionDenied()
    return get_object_or_404(_request_queryset(actor, row.makerspace_id), pk=row.pk)


def _query_int(request, name):
    value = request.query_params.get(name)
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError({name: "Must be an integer."}) from exc


def _response(row, code=status.HTTP_200_OK):
    row = MachineServiceRequest.objects.select_related(
        "makerspace", "bucket__machine__machine_type", "queue__machine_type", "assigned_machine__machine_type", "requester"
    ).prefetch_related("files", "consumptions").get(pk=row.pk)
    return Response(MachineServiceRequestSerializer(row).data, status=code)


class MachineServiceRequestListCreateView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(tags=["Admin machine service"], summary="List machine service requests",
                   parameters=SERVICE_FILTERS,
                   responses={200: MachineServiceRequestSerializer(many=True), **SERVICE_ERRORS})
    def get(self, request, makerspace_id, *args, **kwargs):
        # Reading the list is allowed on the narrow action so a handover role can find
        # what is waiting; `_request_queryset` then trims it to collectable rows for an
        # actor who cannot manage machines. Creating one below still requires management.
        makerspace = _visible_makerspace(
            request.user, makerspace_id, rbac.Action.COLLECT_SERVICE_REQUEST
        )
        rows = _request_queryset(request.user, makerspace.pk).filter(makerspace=makerspace)
        status_value = request.query_params.get("status")
        if status_value not in (None, ""):
            rows = rows.filter(status=status_value)
        for name, field in (("machine", "bucket__machine_id"), ("bucket", "bucket_id"), ("queue", "queue_id")):
            if value := _query_int(request, name):
                rows = rows.filter(**{field: value})
        if machine_type := request.query_params.get("machine_type"):
            rows = rows.filter(Q(queue__machine_type__slug=machine_type) | Q(bucket__machine__machine_type__slug=machine_type))
        rows = list(rows.order_by("-created_at"))
        payments = Payment.objects.filter(
            makerspace=makerspace,
            subject_type=Payment.SubjectType.MACHINE_SERVICE_REQUEST,
            subject_id__in=[row.pk for row in rows],
        )
        payment_map = {payment.subject_id: payment for payment in payments}
        return Response(MachineServiceRequestSerializer(
            rows,
            many=True,
            context={"payments_by_subject_id": payment_map},
        ).data)

    @extend_schema(tags=["Admin machine service"], summary="Submit a machine service request for a member",
                   request=MachineServiceSubmitSerializer,
                   responses={201: MachineServiceRequestSerializer, **SERVICE_ERRORS})
    def post(self, request, makerspace_id, *args, **kwargs):
        makerspace = _visible_makerspace(request.user, makerspace_id)
        serializer = MachineServiceSubmitSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        member = get_object_or_404(
            MakerspaceMembership.objects.select_related("user").filter(
                makerspace=makerspace, user_id=data["requester_id"], user__is_active=True
            )
        )
        machine = get_object_or_404(
            Machine.objects.filter(
                role_scope.scoped_q(request.user, [makerspace.pk]),
                makerspace=makerspace,
            ),
            pk=data["machine_id"],
        )
        requester = member.user
        row = service_workflow.submit(
            machine, requester, actor=request.user,
            member=requester,
            requester_name=data.get("requester_name") or requester.get_full_name().strip() or requester.username,
            contact_email=data.get("contact_email") or requester.email,
            contact_phone=data.get("contact_phone") or requester.phone,
            title=data["title"], description=data.get("description", ""),
            source_link=data.get("source_link", ""),
            capability_payload=data.get("capability_payload"),
        )
        return _response(row, status.HTTP_201_CREATED)


class MachineServiceRequestDetailView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(tags=["Admin machine service"], summary="Retrieve a machine service request",
                   responses={200: MachineServiceRequestSerializer, **SERVICE_ERRORS})
    def get(self, request, pk, *args, **kwargs):
        # Readable on the narrow action: collecting a job you cannot open is not a
        # workflow. `_request_queryset` still hides non-collectable rows from a
        # collect-only actor, so this 404s rather than leaking the queue.
        return _response(
            _manageable_request(request.user, pk, rbac.Action.COLLECT_SERVICE_REQUEST)
        )


class _MachineServiceActionView(APIView):
    permission_classes = [IsActiveStaff]
    input_serializer = EmptyServiceActionSerializer
    operation = None
    # Every operation but collection edits the machine record of what happened, so the
    # default is the broad action; MachineServiceCollectView narrows it.
    required_action = rbac.Action.MANAGE_MACHINES

    def post(self, request, pk, *args, **kwargs):
        row = _manageable_request(request.user, pk, self.required_action)
        serializer = self.input_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        if self.operation == "accept":
            row = service_workflow.accept(row, request.user, **data)
        elif self.operation == "reject":
            row = service_workflow.reject(row, request.user, **data)
        elif self.operation == "start":
            machine_scope = role_scope.manage_scope_for(
                request.user, row.makerspace_id
            )
            row = service_workflow.start(
                row, request.user, machine_scope, **data
            )
        elif self.operation == "complete":
            row = service_workflow.complete(row, request.user, **data)
        elif self.operation == "fail":
            row = service_workflow.fail(row, request.user, **data)
        elif self.operation == "collect":
            row = service_workflow.collect(row, request.user)
        elif self.operation == "reprint":
            row = service_workflow.create_reprint(row, request.user)
        else:
            raise AssertionError("Unknown service action")
        return _response(row)


class MachineServiceAcceptView(_MachineServiceActionView):
    input_serializer, operation = ServiceAcceptSerializer, "accept"

    @extend_schema(tags=["Admin machine service"], summary="Accept a machine service request",
                   request=ServiceAcceptSerializer, responses={200: MachineServiceRequestSerializer, **SERVICE_ERRORS})
    def post(self, request, pk, *args, **kwargs): return super().post(request, pk, *args, **kwargs)


class MachineServiceRejectView(_MachineServiceActionView):
    input_serializer, operation = ServiceRejectSerializer, "reject"

    @extend_schema(tags=["Admin machine service"], summary="Reject a machine service request",
                   request=ServiceRejectSerializer, responses={200: MachineServiceRequestSerializer, **SERVICE_ERRORS})
    def post(self, request, pk, *args, **kwargs): return super().post(request, pk, *args, **kwargs)


class MachineServiceStartView(_MachineServiceActionView):
    input_serializer, operation = ServiceStartSerializer, "start"

    @extend_schema(tags=["Admin machine service"], summary="Start machine service work",
                   request=ServiceStartSerializer, responses={200: MachineServiceRequestSerializer, **SERVICE_ERRORS})
    def post(self, request, pk, *args, **kwargs): return super().post(request, pk, *args, **kwargs)


class MachineServiceCompleteView(_MachineServiceActionView):
    input_serializer, operation = ServiceCompleteSerializer, "complete"

    @extend_schema(tags=["Admin machine service"], summary="Complete machine service work",
                   request=ServiceCompleteSerializer, responses={200: MachineServiceRequestSerializer, **SERVICE_ERRORS})
    def post(self, request, pk, *args, **kwargs): return super().post(request, pk, *args, **kwargs)


class MachineServiceFailView(_MachineServiceActionView):
    input_serializer, operation = ServiceFailSerializer, "fail"

    @extend_schema(tags=["Admin machine service"], summary="Mark machine service work failed",
                   request=ServiceFailSerializer, responses={200: MachineServiceRequestSerializer, **SERVICE_ERRORS})
    def post(self, request, pk, *args, **kwargs): return super().post(request, pk, *args, **kwargs)


class MachineServiceCollectView(_MachineServiceActionView):
    operation = "collect"
    required_action = rbac.Action.COLLECT_SERVICE_REQUEST

    @extend_schema(tags=["Admin machine service"], summary="Mark a machine service request collected",
                   request=EmptyServiceActionSerializer, responses={200: MachineServiceRequestSerializer, **SERVICE_ERRORS})
    def post(self, request, pk, *args, **kwargs): return super().post(request, pk, *args, **kwargs)


class MachineServiceReprintView(_MachineServiceActionView):
    operation = "reprint"

    @extend_schema(tags=["Admin machine service"], summary="Create a printer reprint", request=EmptyServiceActionSerializer, responses={200: MachineServiceRequestSerializer, **SERVICE_ERRORS})
    def post(self, request, pk, *args, **kwargs):
        return super().post(request, pk, *args, **kwargs)
