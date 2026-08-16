"""Staff printer pack endpoints backed exclusively by generic machine kernel rows."""

from django.db.models import Q
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import rbac
from apps.admin_api.permissions import IsActiveStaff
from apps.admin_api.serializers_machine_service_printer import (
    PrinterPoolCorrectionSerializer, PrinterPoolCreateSerializer, PrinterPoolSerializer,
    PrinterPoolVisibilitySerializer, TypedManualUsageResponseSerializer,
    TypedManualUsageSerializer,
)
from apps.admin_api.views_machine_service import _query_int
from apps.machines import role_scope
from apps.machines.models import (
    Machine,
    MachineConsumablePool,
    MachineServiceRequest,
    MachineType,
    MachineUsageEntry,
)
from apps.machines.printer_capabilities import PRINTER_SLUG
from apps.machines.service_consumable_pools import (
    correct_pool,
    create_pool,
    log_typed_manual_usage,
    set_pool_visibility,
)
from apps.makerspaces.guards import require_module
from apps.makerspaces.models import Makerspace


def _space(actor, makerspace_id):
    row = get_object_or_404(rbac.scope_by_makerspace(actor, Makerspace.objects.all(), makerspace_field="id"), pk=makerspace_id)
    require_module(row, "machine_service")
    if not rbac.can(actor, rbac.Action.MANAGE_MACHINES, row.pk):
        raise PermissionDenied()
    return row


def _pool(actor, pk):
    queryset = scoped_pools(
        actor,
        MachineConsumablePool.objects.select_related("makerspace", "machine__machine_type"),
    )
    row = get_object_or_404(queryset, pk=pk)
    require_module(row.makerspace, "machine_service")
    return row


def scoped_pools(actor, queryset):
    """Consumable pools the actor's role scope reaches.

    Machine- and type-scoped pools follow that scope. Pools with neither are
    makerspace-wide shared stock and stay visible to anyone holding MANAGE_MACHINES in
    the space -- they belong to no team, and hiding them would leave shared filament
    unmanageable by everyone rather than by the wrong people.
    """
    queryset = rbac.scope_by_action(
        actor, rbac.Action.MANAGE_MACHINES, queryset, field="makerspace_id"
    )
    manage_scope = rbac.makerspaces_for_action(actor, rbac.Action.MANAGE_MACHINES)
    if manage_scope is rbac.ALL:
        return queryset
    scoped = role_scope.scoped_related_q(
        actor,
        manage_scope,
        machine_id_paths=("machine_id", "machine_type__machines__id"),
        type_id_paths=("machine__machine_type_id", "machine_type_id"),
    )
    shared = Q(machine__isnull=True, machine_type__isnull=True)
    return queryset.filter(scoped | shared).distinct()


def _scoped_types(actor, makerspace):
    authority = role_scope.manage_scope_for(actor, makerspace.pk)
    scope = role_scope.scope_q_for(
        authority,
        machine_id_paths=("machines__id",),
        type_id_paths=("id",),
    )
    available = Q(makerspace__isnull=True) | Q(makerspace=makerspace)
    return MachineType.objects.filter(available).filter(scope).distinct()


class MachineServicePrinterPoolListCreateView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(tags=["Admin machine service"], responses={200: PrinterPoolSerializer(many=True)})
    def get(self, request, makerspace_id):
        space = _space(request.user, makerspace_id)
        rows = scoped_pools(
            request.user,
            MachineConsumablePool.objects.filter(makerspace=space).select_related(
                "machine", "machine_type"
            ),
        ).order_by("material", "color", "id")
        return Response(PrinterPoolSerializer(rows, many=True).data)

    @extend_schema(tags=["Admin machine service"], request=PrinterPoolCreateSerializer, responses={201: PrinterPoolSerializer})
    def post(self, request, makerspace_id):
        space = _space(request.user, makerspace_id)
        serializer = PrinterPoolCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        machine = None
        if machine_id := data.pop("machine_id", None):
            machine = get_object_or_404(
                Machine.objects.select_related("machine_type").filter(
                    role_scope.scoped_q(request.user, [space.pk]),
                    makerspace=space,
                ),
                pk=machine_id,
            )
        machine_type = None
        if machine_type_id := data.pop("machine_type_id", None):
            machine_type = get_object_or_404(
                _scoped_types(request.user, space),
                pk=machine_type_id,
            )
        row = create_pool(
            space,
            request.user,
            machine=machine,
            machine_type=machine_type,
            **data,
        )
        return Response(PrinterPoolSerializer(row).data, status=status.HTTP_201_CREATED)


class MachineServicePrinterPoolDetailView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(tags=["Admin machine service"], responses={200: PrinterPoolSerializer})
    def get(self, request, pk):
        return Response(PrinterPoolSerializer(_pool(request.user, pk)).data)

    @extend_schema(tags=["Admin machine service"], request=PrinterPoolVisibilitySerializer, responses={200: PrinterPoolSerializer})
    def patch(self, request, pk):
        pool = _pool(request.user, pk)
        serializer = PrinterPoolVisibilitySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        row = set_pool_visibility(pool, request.user, **serializer.validated_data)
        return Response(PrinterPoolSerializer(row).data)


class MachineServicePrinterPoolAdjustmentView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(tags=["Admin machine service"], request=PrinterPoolCorrectionSerializer, responses={200: PrinterPoolSerializer})
    def post(self, request, pk):
        pool = _pool(request.user, pk)
        serializer = PrinterPoolCorrectionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        row = correct_pool(pool, request.user, **serializer.validated_data)
        return Response(PrinterPoolSerializer(row).data)


class MachineServiceTypedManualUsageView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(
        tags=["Admin machine service"],
        parameters=[
            OpenApiParameter("machine_type", str, OpenApiParameter.QUERY),
            OpenApiParameter("machine_type_id", int, OpenApiParameter.QUERY),
        ],
        responses={200: TypedManualUsageResponseSerializer(many=True)},
    )
    def get(self, request, makerspace_id):
        space = _space(request.user, makerspace_id)
        rows = MachineUsageEntry.objects.filter(
            role_scope.scoped_related_q(
                request.user,
                [space.pk],
                makerspace_field="machine__makerspace_id",
                machine_id_paths=("machine_id",),
                type_id_paths=("machine__machine_type_id",),
            ),
            machine__makerspace=space,
            source=MachineUsageEntry.Source.TYPED_MANUAL,
        )
        # Prefer the stable id: a slug is not unique across the global/tenant split, so two
        # types sharing one would return each other's usage entries. A malformed value is a
        # 400, never a silent fall-through to the printer default -- returning unrelated data
        # for a bad filter is worse than refusing it.
        if (machine_type_id := _query_int(request, "machine_type_id")) is not None:
            rows = rows.filter(machine__machine_type_id=machine_type_id)
        else:
            machine_type = request.query_params.get("machine_type", PRINTER_SLUG)
            rows = rows.filter(machine__machine_type__slug=machine_type)
        return Response(TypedManualUsageResponseSerializer(rows, many=True).data)

    @extend_schema(tags=["Admin machine service"], request=TypedManualUsageSerializer, responses={201: TypedManualUsageResponseSerializer})
    def post(self, request, makerspace_id):
        space = _space(request.user, makerspace_id)
        serializer = TypedManualUsageSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        machine = get_object_or_404(
            Machine.objects.select_related("machine_type").filter(
                role_scope.scoped_q(request.user, [space.pk]),
                makerspace=space,
            ),
            pk=data.pop("machine_id"),
        )
        pool_id, request_id = data.pop("consumable_pool_id", None), data.pop("service_request_id", None)
        pool = get_object_or_404(
            scoped_pools(request.user, MachineConsumablePool.objects.filter(makerspace=space)),
            pk=pool_id,
        ) if pool_id else None
        service_request = None
        if request_id:
            compatible = (
                Q(assigned_machine_id=machine.pk)
                | Q(assigned_machine__isnull=True, bucket__machine_id=machine.pk)
                | Q(
                    assigned_machine__isnull=True,
                    queue__machine_type_id=machine.machine_type_id,
                )
            )
            service_request = get_object_or_404(
                role_scope.scoped_service_requests(
                    request.user,
                    MachineServiceRequest.objects.filter(
                        compatible,
                        makerspace=space,
                    ),
                    [space.pk],
                ),
                pk=request_id,
            )
        row = log_typed_manual_usage(machine, request.user, pool=pool, service_request=service_request, **data)
        return Response(TypedManualUsageResponseSerializer(row).data, status=status.HTTP_201_CREATED)
