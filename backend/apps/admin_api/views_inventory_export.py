from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework.exceptions import ValidationError
from rest_framework.views import APIView

from apps.accounts import rbac
from apps.admin_api.exports import csv_response, xlsx_response
from apps.admin_api.inventory_filters import apply_inventory_list_filters
from apps.admin_api.permissions import IsActiveStaff, require_action
from apps.inventory.models import InventoryProduct
from apps.makerspaces.guards import require_module

EXPORT_COLUMNS = [
    "name",
    "category",
    "tracking_mode",
    "total_quantity",
    "available_quantity",
    "reserved_quantity",
    "issued_quantity",
    "damaged_quantity",
    "lost_quantity",
    "needs_fix_quantity",
    "is_public",
    "public_availability_mode",
    "show_public_count",
    "public_self_checkout_enabled",
    "storage_location",
    "box_code",
    "is_archived",
    "created_at",
]

ERROR_RESPONSES = {
    400: OpenApiResponse(description="Invalid request."),
    401: OpenApiResponse(description="Authentication credentials were not provided."),
    403: OpenApiResponse(description="Permission denied."),
    404: OpenApiResponse(description="Not found."),
}


class InventoryExportView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(
        tags=["Admin inventory"],
        summary="Export inventory products as CSV or XLSX",
        request=None,
        parameters=[
            OpenApiParameter(
                "format",
                OpenApiTypes.STR,
                OpenApiParameter.QUERY,
                enum=["csv", "xlsx"],
            ),
            OpenApiParameter("ids", OpenApiTypes.STR, OpenApiParameter.QUERY),
            OpenApiParameter(
                "archived",
                OpenApiTypes.STR,
                OpenApiParameter.QUERY,
                enum=["true", "false", "all"],
            ),
            OpenApiParameter("q", OpenApiTypes.STR, OpenApiParameter.QUERY),
            OpenApiParameter(
                "low_stock",
                OpenApiTypes.BOOL,
                OpenApiParameter.QUERY,
            ),
            OpenApiParameter("out_of_stock", OpenApiTypes.STR, enum=["true", "false"],
                             description="Exactly zero available, matching the dashboard list."),
        ],
        responses={
            (200, "text/csv"): OpenApiTypes.STR,
            (
                200,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ): OpenApiTypes.BINARY,
            **ERROR_RESPONSES,
        },
    )
    def get(self, request, makerspace_id, *args, **kwargs):
        require_module(makerspace_id, "staff_admin")
        # EDIT_INVENTORY (not VIEW_INVENTORY): the bulk export carries storage_location
        # and box_code, so it stays a manager surface — handout-only guest admins, who
        # only hold VIEW_INVENTORY, must not be able to pull it.
        require_action(request.user, rbac.Action.EDIT_INVENTORY, makerspace_id)
        fmt = request.query_params.get("format", "csv")
        if fmt not in {"csv", "xlsx"}:
            raise ValidationError({"format": "Use csv or xlsx."})

        queryset = rbac.scope_by_action(
            request.user, rbac.Action.EDIT_INVENTORY, InventoryProduct.objects.all(),
        ).filter(makerspace_id=makerspace_id)
        ids = _parse_ids(request.query_params.get("ids"))
        if request.query_params.get("ids") is not None:
            queryset = queryset.filter(pk__in=ids)
        else:
            queryset = apply_inventory_list_filters(queryset, request.query_params)
        products = queryset.select_related("category", "box").order_by("name")
        rows = _inventory_export_rows(products)

        if fmt == "xlsx":
            return xlsx_response(rows, "inventory-export.xlsx")
        return csv_response(rows, "inventory-export.csv")


def _parse_ids(raw_ids):
    ids = []
    for token in (raw_ids or "").split(","):
        try:
            ids.append(int(token.strip()))
        except ValueError:
            continue
    return ids


def _inventory_export_rows(products):
    rows = [EXPORT_COLUMNS]
    total_quantity = 0
    available_quantity = 0
    count = 0
    for product in products:
        count += 1
        total_quantity += product.total_quantity
        available_quantity += product.available_quantity
        rows.append(_product_row(product))
    summary = [""] * len(EXPORT_COLUMNS)
    summary[0] = f"TOTAL ({count} items)"
    summary[3] = total_quantity
    summary[4] = available_quantity
    rows.append(summary)
    return rows


def _product_row(product):
    return [
        product.name,
        product.category.name if product.category_id else "",
        product.tracking_mode,
        product.total_quantity,
        product.available_quantity,
        product.reserved_quantity,
        product.issued_quantity,
        product.damaged_quantity,
        product.lost_quantity,
        product.needs_fix_quantity,
        product.is_public,
        product.public_availability_mode,
        product.show_public_count,
        product.public_self_checkout_enabled,
        product.storage_location,
        product.box.code if product.box_id else "",
        product.is_archived,
        product.created_at.isoformat(),
    ]
