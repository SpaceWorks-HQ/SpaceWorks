from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import rbac
from apps.admin_api.permissions import IsActiveStaff, require_action
from apps.makerspaces.guards import require_module
from apps.makerspaces.models import Makerspace
from apps.operations import ledger
from apps.operations.report_exports import _csv_response, _xlsx_response
from apps.operations.report_exports_provenance import (
    LEDGER_REPORT_KEY,
    LEDGER_REPORT_VERSION,
    actor_label,
    build_provenance,
    export_filters,
)
from apps.operations.serializers import EmptySerializer, LedgerResponseSerializer
from apps.operations.views_reports import (
    _makerspace_for_inventory_view,
    _page_params,
    _require_superadmin,
)

LEDGER_PARAMETERS = [
    OpenApiParameter("page", OpenApiTypes.INT, OpenApiParameter.QUERY),
    OpenApiParameter("page_size", OpenApiTypes.INT, OpenApiParameter.QUERY),
    OpenApiParameter("search", OpenApiTypes.STR, OpenApiParameter.QUERY),
    OpenApiParameter(
        "source",
        OpenApiTypes.STR,
        OpenApiParameter.QUERY,
        enum=["reviewed", "self_checkout", "direct"],
    ),
    OpenApiParameter("overdue", OpenApiTypes.BOOL, OpenApiParameter.QUERY),
    OpenApiParameter(
        "sort",
        OpenApiTypes.STR,
        OpenApiParameter.QUERY,
        enum=[
            "item_name",
            "-item_name",
            "holder",
            "-holder",
            "quantity",
            "-quantity",
            "since",
            "-since",
            "due",
            "-due",
            "source",
            "-source",
            "makerspace_id",
            "-makerspace_id",
        ],
    ),
]

LEDGER_EXPORT_PARAMETERS = [
    *[parameter for parameter in LEDGER_PARAMETERS if parameter.name not in {"page", "page_size"}],
    OpenApiParameter("format", OpenApiTypes.STR, OpenApiParameter.QUERY, enum=["csv", "xlsx"]),
]

AGGREGATE_LEDGER_PARAMETERS = [
    *LEDGER_PARAMETERS,
    OpenApiParameter("makerspace", OpenApiTypes.INT, OpenApiParameter.QUERY),
]

AGGREGATE_LEDGER_EXPORT_PARAMETERS = [
    *LEDGER_EXPORT_PARAMETERS,
    OpenApiParameter("makerspace", OpenApiTypes.INT, OpenApiParameter.QUERY),
]


class LedgerView(APIView):
    permission_classes = [IsActiveStaff]
    serializer_class = LedgerResponseSerializer

    @extend_schema(
        tags=["Ledger"],
        summary="List outstanding inventory loans",
        request=None,
        parameters=LEDGER_PARAMETERS,
        responses={200: LedgerResponseSerializer},
    )
    def get(self, request, makerspace_id, *args, **kwargs):
        makerspace = _makerspace_for_inventory_view(request.user, makerspace_id)
        require_action(request.user, rbac.Action.VIEW_INVENTORY, makerspace.id)
        require_module(makerspace, "staff_admin")
        return Response(_ledger_payload(makerspace.id, request))


class AggregateLedgerView(APIView):
    permission_classes = [IsActiveStaff]
    serializer_class = LedgerResponseSerializer

    @extend_schema(
        tags=["Ledger"],
        summary="List outstanding inventory loans across all makerspaces",
        request=None,
        parameters=AGGREGATE_LEDGER_PARAMETERS,
        responses={200: LedgerResponseSerializer},
    )
    def get(self, request, *args, **kwargs):
        _require_superadmin(request.user)
        return Response(_ledger_payload(_aggregate_ledger_makerspace_id(request), request))


class LedgerExportView(APIView):
    permission_classes = [IsActiveStaff]
    serializer_class = EmptySerializer

    @extend_schema(
        tags=["Ledger"],
        summary="Export outstanding inventory loans",
        request=None,
        parameters=LEDGER_EXPORT_PARAMETERS,
        responses={
            (200, "text/csv"): OpenApiTypes.STR,
            (200, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"): OpenApiTypes.BINARY,
        },
    )
    def get(self, request, makerspace_id, *args, **kwargs):
        makerspace = _makerspace_for_inventory_view(request.user, makerspace_id)
        require_action(request.user, rbac.Action.VIEW_INVENTORY, makerspace.id)
        require_module(makerspace, "staff_admin")
        return _ledger_export_response(makerspace.id, request, f"ledger-{makerspace.slug}")


class AggregateLedgerExportView(APIView):
    permission_classes = [IsActiveStaff]
    serializer_class = EmptySerializer

    @extend_schema(
        tags=["Ledger"],
        summary="Export outstanding inventory loans across all makerspaces",
        request=None,
        parameters=AGGREGATE_LEDGER_EXPORT_PARAMETERS,
        responses={
            (200, "text/csv"): OpenApiTypes.STR,
            (200, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"): OpenApiTypes.BINARY,
        },
    )
    def get(self, request, *args, **kwargs):
        _require_superadmin(request.user)
        return _ledger_export_response(
            _aggregate_ledger_makerspace_id(request),
            request,
            "ledger-all",
        )


def _ledger_payload(makerspace_id, request):
    page, page_size = _page_params(request)
    payload = ledger.ledger_page(
        makerspace_id,
        page=page,
        page_size=page_size,
        filters=_ledger_filters(request),
    )
    payload.update(_pagination_links(request, page, page_size, payload["count"]))
    serializer = LedgerResponseSerializer(payload)
    return serializer.data


def _ledger_export_response(makerspace_id, request, filename_base):
    fmt = _export_format(request)
    filters = _ledger_filters(request)
    rows = ledger.ledger_export_rows(makerspace_id, filters=filters)
    provenance = build_provenance(
        LEDGER_REPORT_KEY, version=LEDGER_REPORT_VERSION, makerspace_id=makerspace_id,
        generated_by=actor_label(request.user), filters=export_filters(extra=filters),
    )
    if fmt == "xlsx":
        return _xlsx_response(rows, f"{filename_base}.xlsx", provenance=provenance)
    return _csv_response(rows, f"{filename_base}.csv", provenance=provenance)


def _ledger_filters(request):
    search = (request.query_params.get("search") or "").strip()
    if len(search) > 200:
        raise ValidationError({"search": "Search must be 200 characters or fewer."})

    raw_source = (request.query_params.get("source") or "").strip()
    source = None
    if raw_source:
        source = ledger.normalize_source(raw_source)
        if source is None:
            raise ValidationError({"source": "Use reviewed, self_checkout, or direct."})

    raw_sort = (request.query_params.get("sort") or "").strip()
    sort = None
    if raw_sort:
        sort = ledger.normalize_sort(raw_sort)
        if sort is None:
            raise ValidationError({"sort": "Use a supported ledger sort field."})

    return {
        "search": search,
        "source": source,
        "overdue": _bool_param(request, "overdue"),
        "sort": sort,
    }


def _aggregate_ledger_makerspace_id(request):
    raw = (request.query_params.get("makerspace") or "").strip()
    if not raw:
        return None
    try:
        makerspace_id = int(raw)
    except ValueError as exc:
        raise ValidationError({"makerspace": "Enter a makerspace id."}) from exc
    if makerspace_id < 1:
        raise ValidationError({"makerspace": "Enter a makerspace id."})
    excluded = rbac.superadmin_hidden_makerspace_ids() | rbac.archived_makerspace_ids()
    queryset = Makerspace.objects.all()
    if excluded:
        queryset = queryset.exclude(pk__in=excluded)
    if not queryset.filter(pk=makerspace_id).exists():
        raise ValidationError({"makerspace": "Makerspace is not available."})
    return makerspace_id


def _bool_param(request, name):
    raw = (request.query_params.get(name) or "").strip().lower()
    if not raw:
        return None
    if raw in {"1", "true", "yes"}:
        return True
    if raw in {"0", "false", "no"}:
        return False
    raise ValidationError({name: "Use true or false."})


def _pagination_links(request, page, page_size, count):
    next_url = None
    previous_url = None
    if page * page_size < count:
        next_url = _page_url(request, page + 1)
    if page > 1:
        previous_url = _page_url(request, page - 1)
    return {"next": next_url, "previous": previous_url}


def _page_url(request, page):
    params = request.query_params.copy()
    params["page"] = page
    return request.build_absolute_uri(f"{request.path}?{params.urlencode()}")


def _export_format(request):
    fmt = (request.query_params.get("format") or "csv").strip().lower()
    if fmt not in {"csv", "xlsx"}:
        raise ValidationError({"format": "Use csv or xlsx."})
    return fmt


