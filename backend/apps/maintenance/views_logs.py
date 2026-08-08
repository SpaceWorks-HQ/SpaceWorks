from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.admin_api.permissions import IsActiveStaff
from apps.maintenance.serializers import (
    MaintenanceLogListSerializer,
    MaintenanceLogSerializer,
    MaintenanceLogWriteSerializer,
)
from apps.maintenance.views_shared import (
    MaintenancePagination,
    page_response,
    require_machine_access,
    resolve_collection,
)
from apps.hardware_requests.view_helpers import (
    ERROR_400, ERROR_403, ERROR_404, ERROR_409,
)
from apps.maintenance import services
from apps.maintenance.models import MaintenanceLog, MaintenanceSchedule


SCOPED = {400: ERROR_400, 403: ERROR_403, 404: ERROR_404}
MUTATION = {**SCOPED, 409: ERROR_409}


class MaintenanceLogListCreateView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(
        tags=["Admin maintenance"],
        summary="List immutable machine maintenance logs",
        request=None,
        responses={200: MaintenanceLogListSerializer, **SCOPED},
    )
    def get(self, request, makerspace_id, machine_id, *args, **kwargs):
        machine = resolve_collection(
            request.user, makerspace_id, machine_id, manage=False,
        )
        queryset = MaintenanceLog.objects.filter(machine=machine).prefetch_related(
            "documents",
        ).order_by("-performed_at", "-id")
        paginator = MaintenancePagination()
        page = paginator.paginate_queryset(queryset, request, view=self)
        return page_response(paginator, page, MaintenanceLogSerializer)

    @extend_schema(
        tags=["Admin maintenance"],
        summary="Record completed machine maintenance",
        request=MaintenanceLogWriteSerializer,
        responses={201: MaintenanceLogSerializer, **MUTATION},
    )
    def post(self, request, makerspace_id, machine_id, *args, **kwargs):
        machine = resolve_collection(
            request.user, makerspace_id, machine_id, manage=False,
        )
        serializer = MaintenanceLogWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        schedule_id = data.pop("schedule_id", None)
        if schedule_id is not None:
            schedule = get_object_or_404(
                MaintenanceSchedule.objects.filter(machine=machine),
                pk=schedule_id,
            )
            require_machine_access(request.user, machine, manage=True)
            log = services.complete_due(
                schedule, actor=request.user, **data,
            )
        else:
            log = services.log_maintenance(
                machine, actor=request.user, **data,
            )
        log = MaintenanceLog.objects.prefetch_related("documents").get(pk=log.pk)
        return Response(
            MaintenanceLogSerializer(log).data,
            status=status.HTTP_201_CREATED,
        )
