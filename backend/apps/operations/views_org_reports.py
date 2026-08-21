from django.db.models import Exists
from django.shortcuts import get_object_or_404
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework.exceptions import APIException
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.admin_api.permissions import IsActiveStaff
from apps.operations import org_reports, reports
from apps.operations.org_report_scope import (
    OrganizationReportScopeError,
    resolve_organization_report_scope,
)
from apps.operations.serializers_org_reports import OrganizationReportResponseSerializer
from apps.operations.serializers_reports import ReportErrorSerializer
from apps.operations.views_reports import (
    DATE_RANGE_PARAMETERS,
    PAYMENT_FILTER_PARAMETERS,
    _date_range,
    _limit_param,
    _report_filters,
)
from apps.organizations.models import Organization, OrganizationMembership


class InvalidOrganizationReport(APIException):
    status_code = 400

    def __init__(self, error):
        self.detail = {
            "detail": str(error),
            "code": "invalid_organization_report",
        }


ORGANIZATION_REPORT_ERRORS = {
    400: OpenApiResponse(ReportErrorSerializer, description="Invalid or excluded organization report."),
    401: OpenApiResponse(ReportErrorSerializer, description="Authentication required."),
    403: OpenApiResponse(ReportErrorSerializer, description="Permission denied."),
    404: OpenApiResponse(ReportErrorSerializer, description="Organization or report not found."),
}


def _organization_for_report(actor, organization_id, definition):
    """Scope the lookup by the actor's own qualifying grant, like the per-space views do.

    Deliberately 404 -- not 403 -- for a non-existent organization, one the actor is not
    an active member of, AND one whose membership lacks this report's action. Those three
    must be indistinguishable, or organization ids become enumerable by comparing status
    codes. This mirrors _makerspace_for_inventory_view's scoped-lookup convention.

    It also stops an unauthorized actor receiving 200 with an empty body: without this,
    resolve_organization_report_scope simply returns an empty scope, so "you may not" and
    "you own nothing" would look identical to the caller.
    """
    qualifying = OrganizationMembership.objects.filter(
        organization_id=organization_id,
        organization__is_active=True,
        user=actor,
        status=OrganizationMembership.Status.ACTIVE,
        granted_actions__contains=[definition.required_action],
    )
    return get_object_or_404(
        Organization.objects.filter(pk=organization_id).filter(Exists(qualifying))
    )


class OrganizationAnalyticsView(APIView):
    """Return inseparable per-space and combined views of one organization report."""

    # IsActiveStaff, not IsAuthenticated: active_user() also refuses a restricted or
    # suspended account and one carrying must_change_password, any of which can still
    # hold a valid access token. It does NOT require a local MakerspaceMembership, so
    # organization-derived actors are unaffected -- the name is about account status.
    #
    # It also applies staff_origin_scope_allows. This route is TARGETLESS (it takes an
    # organization, not a makerspace), and _global_endpoint_allowed admits only
    # 'admin-makerspaces' (makerspaces/origin_scope.py:169-171), so on a hard-scoped
    # tenant staff origin this route is refused. That is deliberate and must not be
    # "fixed" by widening the allowlist: a tenant-locked origin has no business serving
    # cross-makerspace organization aggregates. The console panel gates itself the same
    # way the organized-events tab does.
    permission_classes = [IsActiveStaff]
    serializer_class = OrganizationReportResponseSerializer

    @extend_schema(
        tags=["Analytics"],
        summary="Get organization analytics report",
        description=(
            "Requires an active organization membership carrying the report's action. "
            "Authorization and the owned-makerspace set are resolved server-side; a "
            "combined total is always returned together with its per-makerspace breakdown."
        ),
        request=None,
        parameters=[
            OpenApiParameter(
                "report_key", OpenApiTypes.STR, OpenApiParameter.PATH,
                enum=sorted(org_reports.organization_strategy_keys()),
            ),
            OpenApiParameter("limit", OpenApiTypes.INT, OpenApiParameter.QUERY),
            *DATE_RANGE_PARAMETERS,
            *PAYMENT_FILTER_PARAMETERS,
        ],
        responses={
            200: OrganizationReportResponseSerializer,
            **ORGANIZATION_REPORT_ERRORS,
        },
    )
    def get(self, request, organization_id, report_key, *args, **kwargs):
        definition = reports.validate_report_key(report_key)
        organization = _organization_for_report(
            request.user, organization_id, definition
        )
        try:
            scope = resolve_organization_report_scope(
                request.user, organization, definition
            )
            data = org_reports.organization_report_data(
                definition,
                scope,
                limit=_limit_param(request),
                date_range=_date_range(request),
                report_filters=_report_filters(request, report_key),
            )
        except (OrganizationReportScopeError, org_reports.OrganizationAggregationError) as exc:
            raise InvalidOrganizationReport(exc) from exc
        return Response(data)
