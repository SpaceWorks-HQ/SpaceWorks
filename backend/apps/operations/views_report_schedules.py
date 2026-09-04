from django.http import Http404
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_view
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import rbac
from apps.admin_api.permissions import IsActiveStaff, require_action
from apps.audit import services as audit
from apps.makerspaces.guards import require_module
from apps.operations.models_report_schedules import ReportSchedule
from apps.operations.report_delivery_storage import delete_report_object
from apps.operations.report_registry import REPORT_DEFINITIONS, REPORT_REGISTRY
from apps.operations.report_schedule_services import run_schedule
from apps.operations.serializers_report_schedules import (
    ReportDeliverySerializer,
    ReportScheduleSerializer,
)
from apps.operations.serializers_reports import ReportErrorSerializer
from apps.operations.views_report_helpers import _makerspace_for_catalog

ERROR_RESPONSES = {
    400: OpenApiResponse(ReportErrorSerializer, description="Invalid schedule or module disabled."),
    403: OpenApiResponse(ReportErrorSerializer, description="Permission denied."),
    404: OpenApiResponse(ReportErrorSerializer, description="Makerspace or schedule not found."),
}


def _scoped_schedule(user, pk):
    """Resolve a schedule through the RBAC scope of ITS report's action (404 otherwise)."""
    report_key = ReportSchedule.objects.filter(pk=pk).values_list("report_key", flat=True).first()
    if report_key is None:
        raise Http404
    definition = REPORT_REGISTRY.get(report_key)
    action = definition.required_action if definition else rbac.Action.MANAGE_MAKERSPACE
    queryset = rbac.scope_by_action(
        user, action, ReportSchedule.objects.select_related("makerspace", "destination", "created_by")
    )
    schedule = get_object_or_404(rbac.hide_from_superadmin(user, queryset), pk=pk)
    require_module(schedule.makerspace, "reports")
    return schedule


@extend_schema_view(
    get=extend_schema(
        tags=["Reports"], summary="List report schedules", request=None,
        responses={200: ReportScheduleSerializer(many=True), **ERROR_RESPONSES},
    ),
    post=extend_schema(
        tags=["Reports"], summary="Create report schedule", request=ReportScheduleSerializer,
        responses={201: ReportScheduleSerializer, **ERROR_RESPONSES},
    ),
)
class ReportScheduleListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsActiveStaff]
    serializer_class = ReportScheduleSerializer

    def _makerspace(self):
        if not hasattr(self, "_resolved_makerspace"):
            makerspace = _makerspace_for_catalog(self.request.user, self.kwargs["makerspace_id"])
            require_module(makerspace, "reports")
            self._resolved_makerspace = makerspace
        return self._resolved_makerspace

    def get_serializer_context(self):
        return {**super().get_serializer_context(), "makerspace": self._makerspace()}

    def get_queryset(self):
        makerspace = self._makerspace()
        # Only schedules for reports this actor may run: a MANAGE_MAKERSPACE-only report's
        # schedule is invisible to a VIEW_AUDIT holder, exactly like the catalog.
        keys = [
            definition.key for definition in REPORT_DEFINITIONS
            if rbac.can(self.request.user, definition.required_action, makerspace.id)
        ]
        return (
            ReportSchedule.objects.filter(makerspace=makerspace, report_key__in=keys)
            .select_related("destination", "created_by")
            .order_by("-created_at", "-id")
        )

    def perform_create(self, serializer):
        makerspace = self._makerspace()
        definition = REPORT_REGISTRY[serializer.validated_data["report_key"]]
        require_action(self.request.user, definition.required_action, makerspace.id)
        schedule = serializer.save(makerspace=makerspace, created_by=self.request.user)
        audit.record(
            self.request.user, "report_schedule.created", makerspace=makerspace, target=schedule,
            meta={"schedule_id": schedule.pk, "report_key": schedule.report_key},
        )


class ReportScheduleDetailView(APIView):
    permission_classes = [IsActiveStaff]
    serializer_class = ReportScheduleSerializer

    @extend_schema(
        tags=["Reports"], summary="Update report schedule", request=ReportScheduleSerializer,
        responses={200: ReportScheduleSerializer, **ERROR_RESPONSES},
    )
    def patch(self, request, pk, *args, **kwargs):
        schedule = _scoped_schedule(request.user, pk)
        context = {"request": request, "makerspace": schedule.makerspace}
        serializer = ReportScheduleSerializer(schedule, data=request.data, partial=True, context=context)
        serializer.is_valid(raise_exception=True)
        new_key = serializer.validated_data.get("report_key", schedule.report_key)
        require_action(request.user, REPORT_REGISTRY[new_key].required_action, schedule.makerspace_id)
        schedule = serializer.save()
        audit.record(
            request.user, "report_schedule.updated", makerspace=schedule.makerspace, target=schedule,
            meta={"schedule_id": schedule.pk, "report_key": schedule.report_key},
        )
        return Response(ReportScheduleSerializer(schedule, context=context).data)

    @extend_schema(
        tags=["Reports"], summary="Delete report schedule", request=None,
        responses={204: None, **ERROR_RESPONSES},
    )
    def delete(self, request, pk, *args, **kwargs):
        schedule = _scoped_schedule(request.user, pk)
        keys = list(schedule.deliveries.exclude(object_key="").values_list("object_key", flat=True))
        audit.record(
            request.user, "report_schedule.deleted", makerspace=schedule.makerspace, target=schedule,
            meta={"schedule_id": schedule.pk, "report_key": schedule.report_key},
        )
        schedule.delete()
        for key in keys:
            delete_report_object(key)
        return Response(status=status.HTTP_204_NO_CONTENT)


class ReportScheduleRunNowView(APIView):
    permission_classes = [IsActiveStaff]
    serializer_class = ReportDeliverySerializer

    @extend_schema(
        tags=["Reports"], summary="Run a report schedule now", request=None,
        responses={
            200: ReportDeliverySerializer,
            409: OpenApiResponse(ReportErrorSerializer, description="Schedule inactive or skipped."),
            **ERROR_RESPONSES,
        },
    )
    def post(self, request, pk, *args, **kwargs):
        schedule = _scoped_schedule(request.user, pk)
        require_action(request.user, REPORT_REGISTRY[schedule.report_key].required_action, schedule.makerspace_id)
        delivery = run_schedule(schedule.pk, force=True, actor=request.user)
        if delivery is None:
            return Response(
                {"detail": "Schedule is inactive or was skipped.", "code": "report_schedule_skipped"},
                status=status.HTTP_409_CONFLICT,
            )
        return Response(ReportDeliverySerializer(delivery).data)
