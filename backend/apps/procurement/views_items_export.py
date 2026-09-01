from django.shortcuts import get_object_or_404
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.views import APIView

from apps.admin_api.exports import csv_response, xlsx_response
from apps.admin_api.permissions import IsActiveStaff
from apps.makerspaces.guards import require_module
from apps.makerspaces.models import Makerspace
from apps.procurement import access
from apps.procurement.models import ToBuyItem
from apps.procurement.serializers import ToBuyItemSerializer
from apps.procurement.views_common import (
    MODULE_KEY,
    PROCUREMENT_ERROR_RESPONSES,
    STATUS_PARAM,
    apply_status_filter,
)


@extend_schema(tags=["Procurement"])
class ToBuyExportView(APIView):
    permission_classes = [IsActiveStaff]
    serializer_class = ToBuyItemSerializer

    @extend_schema(
        summary="Export to-buy items as CSV or XLSX",
        parameters=[
            STATUS_PARAM,
            OpenApiParameter(
                "format", OpenApiTypes.STR, OpenApiParameter.QUERY, enum=["csv", "xlsx"]
            ),
        ],
        responses={
            (200, "text/csv"): OpenApiTypes.STR,
            (200, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"): OpenApiTypes.BINARY,
            **PROCUREMENT_ERROR_RESPONSES,
        },
    )
    def get(self, request, makerspace_id, *args, **kwargs):
        require_module(get_object_or_404(Makerspace, pk=makerspace_id), MODULE_KEY)
        if not access.viewable_kinds(request.user, makerspace_id):
            raise PermissionDenied()
        fmt = request.query_params.get("format", "csv")
        if fmt not in {"csv", "xlsx"}:
            raise ValidationError({"format": "Use csv or xlsx."})
        items = access.scope_items(ToBuyItem.objects.all(), request.user, makerspace_id)
        items = (
            apply_status_filter(items, request)
            .select_related("created_by", "purchaser", "machine_type")
            .order_by("-created_at", "-id")
        )
        rows = [[
            "kind", "machine_type", "name", "quantity", "link", "status",
            "estimated_unit_cost", "vendor_name", "actual_unit_cost", "purchaser",
            "ordered_at", "received_at", "added_by", "created_at",
        ]]
        for item in items:
            rows.append([
                item.kind,
                item.machine_type.name if item.machine_type else "Unassigned",
                item.name,
                item.quantity,
                item.link,
                item.status,
                item.estimated_unit_cost if item.estimated_unit_cost is not None else "",
                item.vendor_name,
                item.actual_unit_cost if item.actual_unit_cost is not None else "",
                item.purchaser.username if item.purchaser else "",
                item.ordered_at.isoformat() if item.ordered_at else "",
                item.received_at.isoformat() if item.received_at else "",
                item.created_by.username if item.created_by else "",
                item.created_at.isoformat(),
            ])
        if fmt == "xlsx":
            return xlsx_response(rows, "to-buy.xlsx")
        return csv_response(rows, "to-buy.csv")
