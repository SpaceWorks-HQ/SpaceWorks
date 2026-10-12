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
from apps.accounts import rbac
from apps.openapi_errors import errors
from apps.maintenance import services
from apps.maintenance.models import MaintenanceLog, MaintenanceSchedule


SCOPED = errors(400, 401, 403, 404)
MUTATION = {**SCOPED, **errors(409, 423)}


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
        queryset = rbac.scope_by_makerspace(
            request.user, MaintenanceLog.objects.all(), makerspace_field="machine__makerspace_id",
        ).filter(machine=machine).prefetch_related(
            "documents",
        ).order_by("-performed_at", "-id")
        paginator = MaintenancePagination()
        page = paginator.paginate_queryset(queryset, request, view=self)
        return page_response(paginator, page, MaintenanceLogSerializer)

    @extend_schema(
        tags=["Admin maintenance"],
        summary="Record completed machine maintenance",
        description=(
            "When schedule_id is supplied, complete that schedule and set its next due "
            "date according to its recurrence anchor. Completion anchors add interval_days "
            "to the makerspace-local date of performed_at; calendar anchors advance the "
            "previous due date by whole intervals past completion. performed_at defaults "
            "to now; backdated entries use their recorded completion date."
        ),
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
                rbac.scope_by_makerspace(
                    request.user, MaintenanceSchedule.objects.all(),
                    makerspace_field="machine__makerspace_id",
                ).filter(machine=machine),
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
        log = rbac.scope_by_makerspace(
            request.user, MaintenanceLog.objects.prefetch_related("documents"),
            makerspace_field="machine__makerspace_id",
        ).get(pk=log.pk)
        return Response(
            MaintenanceLogSerializer(log).data,
            status=status.HTTP_201_CREATED,
        )
