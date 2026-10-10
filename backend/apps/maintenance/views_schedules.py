from django.utils import timezone
from apps.makerspaces.local_time import to_local
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.admin_api.permissions import IsActiveStaff
from apps.maintenance.serializers import (
    EmptyActionSerializer,
    MaintenanceScheduleListSerializer,
    MaintenanceScheduleSerializer,
    MaintenanceScheduleWriteSerializer,
)
from apps.maintenance.views_shared import (
    MaintenancePagination,
    page_response,
    resolve_collection,
    resolve_schedule,
)
from apps.accounts import rbac
from apps.openapi_errors import errors
from apps.maintenance import services
from apps.maintenance.models import MaintenanceSchedule


SCOPED = errors(400, 401, 403, 404)
MUTATION = {**SCOPED, **errors(409, 423)}


class MaintenanceScheduleListCreateView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(
        tags=["Admin maintenance"],
        summary="List machine maintenance schedules",
        request=None,
        responses={200: MaintenanceScheduleListSerializer, **SCOPED},
    )
    def get(self, request, makerspace_id, machine_id, *args, **kwargs):
        machine = resolve_collection(
            request.user, makerspace_id, machine_id, manage=False,
        )
        queryset = rbac.scope_by_makerspace(
            request.user, MaintenanceSchedule.objects.all(),
            makerspace_field="machine__makerspace_id",
        ).filter(machine=machine).order_by(
            "next_due", "id",
        )
        paginator = MaintenancePagination()
        page = paginator.paginate_queryset(queryset, request, view=self)
        return page_response(
            paginator, page, MaintenanceScheduleSerializer,
            context={"today": to_local(machine.makerspace, timezone.now()).date()},
        )

    @extend_schema(
        tags=["Admin maintenance"],
        summary="Create a machine maintenance schedule",
        request=MaintenanceScheduleWriteSerializer,
        responses={201: MaintenanceScheduleSerializer, **MUTATION},
    )
    def post(self, request, makerspace_id, machine_id, *args, **kwargs):
        machine = resolve_collection(
            request.user, makerspace_id, machine_id, manage=True,
        )
        serializer = MaintenanceScheduleWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        schedule = services.create_schedule(
            machine, actor=request.user, **serializer.validated_data,
        )
        return Response(
            MaintenanceScheduleSerializer(
                schedule, context={"today": to_local(machine.makerspace, timezone.now()).date()},
            ).data,
            status=status.HTTP_201_CREATED,
        )


class MaintenanceScheduleDetailView(APIView):
    permission_classes = [IsActiveStaff]
    http_method_names = ["patch", "options"]

    @extend_schema(
        tags=["Admin maintenance"],
        summary="Update a maintenance schedule",
        request=MaintenanceScheduleWriteSerializer,
        responses={200: MaintenanceScheduleSerializer, **MUTATION},
    )
    def patch(self, request, pk, *args, **kwargs):
        schedule = resolve_schedule(request.user, pk, manage=True)
        serializer = MaintenanceScheduleWriteSerializer(
            data=request.data, partial=True,
        )
        serializer.is_valid(raise_exception=True)
        schedule = services.update_schedule(
            schedule, actor=request.user, **serializer.validated_data,
        )
        return Response(MaintenanceScheduleSerializer(
            schedule, context={"today": to_local(schedule.machine.makerspace, timezone.now()).date()},
        ).data)


class MaintenanceScheduleDeactivateView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(
        tags=["Admin maintenance"],
        summary="Deactivate a maintenance schedule",
        request=EmptyActionSerializer,
        responses={200: MaintenanceScheduleSerializer, **MUTATION},
    )
    def post(self, request, pk, *args, **kwargs):
        schedule = resolve_schedule(request.user, pk, manage=True)
        serializer = EmptyActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        schedule = services.deactivate_schedule(schedule, actor=request.user)
        return Response(MaintenanceScheduleSerializer(
            schedule, context={"today": to_local(schedule.machine.makerspace, timezone.now()).date()},
        ).data)
