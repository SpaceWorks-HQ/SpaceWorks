from datetime import datetime, time, timedelta

from django.utils import timezone
from django.utils.dateparse import parse_date
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, PolymorphicProxySerializer, extend_schema
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import rbac
from apps.machines import role_scope
from apps.accounts.models import User
from apps.admin_api.permissions import IsActiveStaff
from apps.hardware_requests.exceptions import ErrorSerializer
from apps.machines.service_reports import build_machine_service_report, build_printer_service_report, report_sections
from apps.machines.service_reports_serializers import MachineServiceReportSerializer, PrinterServiceReportSerializer
from apps.makerspaces.guards import require_module


DATE_RANGE_PARAMETERS = [
    OpenApiParameter("start", OpenApiTypes.DATE, OpenApiParameter.QUERY),
    OpenApiParameter("end", OpenApiTypes.DATE, OpenApiParameter.QUERY),
    OpenApiParameter("machine_type", str, OpenApiParameter.QUERY),
]
REPORT_RESPONSE = PolymorphicProxySerializer(
    component_name="MachineServiceReportResponse",
    serializers=[MachineServiceReportSerializer, PrinterServiceReportSerializer],
    resource_type_field_name=None,
)

ERROR_RESPONSES = {
    400: OpenApiResponse(ErrorSerializer, description="Invalid request."),
    401: OpenApiResponse(description="Authentication credentials were not provided."),
    403: OpenApiResponse(description="Machine management permission required."),
    404: OpenApiResponse(description="Not found."),
}


class MakerspaceMachineServiceReportView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(tags=["Admin machine service"], summary="Retrieve makerspace machine-service report", request=None, parameters=DATE_RANGE_PARAMETERS, responses={200: REPORT_RESPONSE, **ERROR_RESPONSES})
    def get(self, request, makerspace_id, *args, **kwargs):
        # Authorize before the module check so a foreign/hidden makerspace returns a
        # uniform 403 and never leaks its module state via a 400-vs-403 difference.
        if not rbac.can(request.user, rbac.Action.MANAGE_MACHINES, makerspace_id):
            raise PermissionDenied()
        require_module(makerspace_id, "machine_service")
        # The report carries per-machine hours, consumption and payment snapshots, so it
        # is narrowed to the machines this role actually runs. An exempt actor (space
        # manager, superadmin) resolves to an empty filter and sees the whole lab.
        machine_scope = role_scope.manage_scope_for(request.user, makerspace_id)
        if request.query_params.get("machine_type") == "3d_printer":
            result = build_printer_service_report(
                makerspace_id, date_range=_date_range(request), machine_scope=machine_scope
            )
            return Response(PrinterServiceReportSerializer({"printer_metrics": result.records}).data)
        return Response(MachineServiceReportSerializer(report_sections(build_machine_service_report(makerspace_id, date_range=_date_range(request), machine_scope=machine_scope))).data)


class SuperadminMachineServiceReportView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(tags=["Admin machine service"], summary="Retrieve aggregate machine-service report", request=None, parameters=DATE_RANGE_PARAMETERS, responses={200: REPORT_RESPONSE, **ERROR_RESPONSES})
    def get(self, request, *args, **kwargs):
        if not _is_superadmin(request.user):
            raise PermissionDenied()
        if request.query_params.get("machine_type") == "3d_printer":
            result = build_printer_service_report(None, date_range=_date_range(request))
            return Response(PrinterServiceReportSerializer({"printer_metrics": result.records}).data)
        return Response(MachineServiceReportSerializer(report_sections(build_machine_service_report(None, date_range=_date_range(request)))).data)


def _is_superadmin(user):
    return bool(getattr(user, "is_superuser", False) or getattr(user, "role", None) == User.Role.SUPERADMIN)


def _date_range(request):
    start, end = _date_param(request, "start"), _date_param(request, "end")
    if start and end and start > end:
        raise ValidationError({"end": "End date must be on or after start date."})
    start_dt = timezone.make_aware(datetime.combine(start, time.min)) if start else None
    end_dt = timezone.make_aware(datetime.combine(end + timedelta(days=1), time.min)) if end else None
    return (start_dt, end_dt) if start_dt or end_dt else None


def _date_param(request, name):
    raw = (request.query_params.get(name) or "").strip()
    if not raw:
        return None
    parsed = parse_date(raw)
    if parsed is None:
        raise ValidationError({name: "Use YYYY-MM-DD."})
    return parsed
