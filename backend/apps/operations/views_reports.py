from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import rbac
from apps.admin_api.permissions import IsActiveStaff, require_action
from apps.makerspaces.guards import require_module
from apps.makerspaces.platform import module_enabled
from apps.operations import accountability, reports
from apps.operations.org_report_strategies import STRATEGIES
from apps.operations.report_registry import REPORT_DEFINITIONS
from apps.operations.report_exports import _csv_response, _xlsx_cell, _xlsx_response
from apps.operations.schemas_reports import ANALYTICS_REPORT_RESPONSE
from apps.operations.serializers import EmptySerializer, GenericObjectSerializer
from apps.operations.serializers_reports import ReportErrorSerializer
from apps.operations.serializers_report_catalog import ReportCatalogSerializer
from apps.operations.serializers_reports_payments import PaymentReportFilterSerializer
from apps.payments.models import Payment
from apps.operations.views_report_helpers import (
    _date_range,
    _limit_param,
    _makerspace_for_catalog,
    _makerspace_for_inventory_view,
    _page_params,
    _require_source_modules,
    _require_superadmin,
)


DATE_RANGE_PARAMETERS = [
    OpenApiParameter("start", OpenApiTypes.DATE, OpenApiParameter.QUERY),
    OpenApiParameter("end", OpenApiTypes.DATE, OpenApiParameter.QUERY),
]
PAYMENT_FILTER_PARAMETERS = [
    OpenApiParameter("status", OpenApiTypes.STR, OpenApiParameter.QUERY, enum=Payment.Status.values),
    OpenApiParameter("subject_type", OpenApiTypes.STR, OpenApiParameter.QUERY, enum=Payment.SubjectType.values),
]
PREVIEW_PARAMETERS = [
    OpenApiParameter("limit", OpenApiTypes.INT, OpenApiParameter.QUERY),
    *DATE_RANGE_PARAMETERS,
    *PAYMENT_FILTER_PARAMETERS,
    OpenApiParameter("grain", OpenApiTypes.STR, OpenApiParameter.QUERY, enum=["day", "month"]),
]
ERROR_RESPONSES = {
    400: OpenApiResponse(ReportErrorSerializer, description="Invalid report request."),
    401: OpenApiResponse(ReportErrorSerializer, description="Authentication required."),
    403: OpenApiResponse(ReportErrorSerializer, description="Permission denied."),
    404: OpenApiResponse(ReportErrorSerializer, description="Makerspace or report not found."),
}
EXPORT_RESPONSES = {
    (200, "text/csv"): OpenApiTypes.STR,
    (200, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"): OpenApiTypes.BINARY,
    **ERROR_RESPONSES,
}


class AnalyticsView(APIView):
    permission_classes = [IsActiveStaff]
    serializer_class = GenericObjectSerializer

    @extend_schema(
        tags=["Analytics"], summary="Get analytics report", request=None,
        parameters=PREVIEW_PARAMETERS,
        responses={200: ANALYTICS_REPORT_RESPONSE, **ERROR_RESPONSES},
    )
    def get(self, request, makerspace_id, report_key="summary", *args, **kwargs):
        # Inventory-first resolution, deliberately: scoping the queryset by the REPORT's
        # own action would turn "you may not run this report" into a 404 instead of a
        # 403, which is the contract pinned by
        # test_report_rbac_status_codes_match_inventory_first_resolution.
        makerspace = _makerspace_for_inventory_view(request.user, makerspace_id)
        definition = reports.validate_report_key(report_key)
        require_action(request.user, definition.required_action, makerspace.id)
        require_module(makerspace, "reports")
        _require_source_modules(makerspace, definition.required_modules)
        return Response(reports.report_data(
            report_key, makerspace.id,
            limit=_limit_param(request), date_range=_date_range(request),
            report_filters=_report_filters(request, report_key), grain=_grain_param(request, definition),
        ))


class ReportCatalogView(APIView):
    permission_classes = [IsActiveStaff]
    serializer_class = ReportCatalogSerializer

    @extend_schema(
        tags=["Reports"], summary="List makerspace report catalog", request=None,
        responses={200: ReportCatalogSerializer, **ERROR_RESPONSES},
    )
    def get(self, request, makerspace_id, *args, **kwargs):
        makerspace = _makerspace_for_catalog(request.user, makerspace_id)
        require_module(makerspace, "reports")
        entries = []
        for definition in REPORT_DEFINITIONS:
            if not rbac.can(request.user, definition.required_action, makerspace.id):
                continue
            missing = [key for key in definition.required_modules if not module_enabled(makerspace, key)]
            entries.append(_catalog_entry(
                definition, available=not missing,
                reason=f"Required module disabled: {', '.join(missing)}" if missing else None,
            ))
        return Response({"results": entries})


class AggregateReportCatalogView(APIView):
    permission_classes = [IsActiveStaff]
    serializer_class = ReportCatalogSerializer

    @extend_schema(
        tags=["Reports"], summary="List deployment report catalog", request=None,
        responses={200: ReportCatalogSerializer, **ERROR_RESPONSES},
    )
    def get(self, request, *args, **kwargs):
        _require_superadmin(request.user)
        return Response({"results": [
            _catalog_entry(definition, available=None, reason=None)
            for definition in REPORT_DEFINITIONS
        ]})


class AccountabilityReportView(APIView):
    permission_classes = [IsActiveStaff]
    serializer_class = GenericObjectSerializer

    @extend_schema(
        tags=["Analytics"], summary="Requester accountability dashboard",
        request=None, responses={200: OpenApiTypes.OBJECT, **ERROR_RESPONSES},
    )
    def get(self, request, makerspace_id, *args, **kwargs):
        makerspace = _makerspace_for_inventory_view(request.user, makerspace_id)
        require_action(request.user, rbac.Action.VIEW_AUDIT, makerspace.id)
        require_module(makerspace, "reports")
        return Response(accountability.accountability_data(makerspace.id))


class AggregateAnalyticsView(APIView):
    permission_classes = [IsActiveStaff]
    serializer_class = GenericObjectSerializer

    @extend_schema(
        tags=["Analytics"], summary="Get aggregate analytics report", request=None,
        parameters=[
            OpenApiParameter("report_key", OpenApiTypes.STR, OpenApiParameter.PATH, enum=reports.REPORT_KEYS),
            *PREVIEW_PARAMETERS,
        ],
        responses={200: ANALYTICS_REPORT_RESPONSE, **ERROR_RESPONSES},
    )
    def get(self, request, report_key="summary", *args, **kwargs):
        _require_superadmin(request.user)
        reports.validate_report_key(report_key)
        return Response(reports.report_data(
            report_key, limit=_limit_param(request), date_range=_date_range(request),
            report_filters=_report_filters(request, report_key),
            grain=_grain_param(request, reports.validate_report_key(report_key)),
        ))


class ReportExportView(APIView):
    permission_classes = [IsActiveStaff]
    serializer_class = EmptySerializer

    @extend_schema(
        tags=["Reports"], summary="Export report", request=None,
        parameters=[
            OpenApiParameter("report_key", OpenApiTypes.STR, OpenApiParameter.PATH, enum=reports.REPORT_KEYS),
            OpenApiParameter("format", OpenApiTypes.STR, OpenApiParameter.QUERY, enum=["csv", "xlsx"]),
            *DATE_RANGE_PARAMETERS,
            *PAYMENT_FILTER_PARAMETERS,
            OpenApiParameter("grain", OpenApiTypes.STR, OpenApiParameter.QUERY, enum=["day", "month"]),
        ],
        responses=EXPORT_RESPONSES,
    )
    def get(self, request, makerspace_id, report_key, *args, **kwargs):
        # Inventory-first resolution, deliberately: scoping the queryset by the REPORT's
        # own action would turn "you may not run this report" into a 404 instead of a
        # 403, which is the contract pinned by
        # test_report_rbac_status_codes_match_inventory_first_resolution.
        makerspace = _makerspace_for_inventory_view(request.user, makerspace_id)
        definition = reports.validate_report_key(report_key, for_export=True)
        require_action(request.user, definition.required_action, makerspace.id)
        require_module(makerspace, "reports")
        _require_source_modules(makerspace, definition.required_modules)
        fmt = _export_format(request)
        rows = reports.report_rows(
            report_key, makerspace.id, date_range=_date_range(request),
            report_filters=_report_filters(request, report_key),
            grain=_grain_param(request, definition),
        )
        return _xlsx_response(rows, f"{report_key}.xlsx") if fmt == "xlsx" else _csv_response(rows, f"{report_key}.csv")


class AggregateReportExportView(APIView):
    permission_classes = [IsActiveStaff]
    serializer_class = EmptySerializer

    @extend_schema(
        tags=["Reports"], summary="Export aggregate report", request=None,
        parameters=[
            OpenApiParameter("report_key", OpenApiTypes.STR, OpenApiParameter.PATH, enum=reports.REPORT_KEYS),
            OpenApiParameter("format", OpenApiTypes.STR, OpenApiParameter.QUERY, enum=["csv", "xlsx"]),
            *DATE_RANGE_PARAMETERS,
            *PAYMENT_FILTER_PARAMETERS,
            OpenApiParameter("grain", OpenApiTypes.STR, OpenApiParameter.QUERY, enum=["day", "month"]),
        ],
        responses=EXPORT_RESPONSES,
    )
    def get(self, request, report_key, *args, **kwargs):
        _require_superadmin(request.user)
        reports.validate_report_key(report_key, for_export=True)
        fmt = _export_format(request)
        rows = reports.report_rows(
            report_key, date_range=_date_range(request),
            report_filters=_report_filters(request, report_key),
            grain=_grain_param(request, reports.validate_report_key(report_key)),
        )
        return _xlsx_response(rows, f"{report_key}.xlsx") if fmt == "xlsx" else _csv_response(rows, f"{report_key}.csv")


def report_data(makerspace_id, report_key):
    return reports.report_data(report_key, makerspace_id)


def report_rows(makerspace_id, report_key):
    return reports.report_rows(report_key, makerspace_id)


def _export_format(request):
    fmt = (request.query_params.get("format") or "csv").strip().lower()
    if fmt not in {"csv", "xlsx"}:
        raise ValidationError({"format": "Use csv or xlsx."})
    return fmt


def _report_filters(request, report_key):
    if report_key != "payment-reconciliation":
        return {}
    serializer = PaymentReportFilterSerializer(data=request.query_params)
    serializer.is_valid(raise_exception=True)
    return serializer.validated_data


def _grain_param(request, definition):
    value = (request.query_params.get("grain") or "day").strip().lower()
    allowed = definition.grains or ("day",)
    if value not in allowed:
        raise ValidationError({"grain": f"Use one of: {', '.join(allowed)}."})
    return value


def _catalog_entry(definition, *, available, reason):
    return {
        "key": definition.key, "title": definition.title or definition.key.replace("-", " ").title(),
        "fields": list(definition.fields), "exportable": definition.exportable,
        "summary": definition.summary, "required_modules": list(definition.required_modules),
        "available": available, "unavailable_reason": reason,
        "grains": list(definition.grains or ("day",)), "chart_hint": definition.chart_hint,
        "aggregate_supported": definition.key in STRATEGIES,
    }
