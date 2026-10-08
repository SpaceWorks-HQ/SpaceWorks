"""Request parsing shared by the report preview, export and organization views.

Split out of ``views_reports`` (phase 10) so the views stay under the file ceiling; the
names are re-exported there, where existing callers import them.
"""

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter
from rest_framework.exceptions import ValidationError

from apps.operations.serializers_reports_payments import PaymentReportFilterSerializer
from apps.payments.models import Payment


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
