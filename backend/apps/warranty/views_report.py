from datetime import timedelta
from math import ceil

from django.db.models import Count, Q
from django.db.models.functions import Lower
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, OpenApiTypes, extend_schema
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.utils.urls import replace_query_param
from rest_framework.views import APIView

from apps.accounts import rbac
from apps.admin_api.permissions import IsActiveStaff
from apps.warranty.serializers import (
    WarrantyReportQuerySerializer,
    WarrantyReportRowSerializer,
)
from apps.admin_api.views_inventory import InventoryPagination
from apps.inventory.models import InventoryAsset
from apps.makerspaces.models import Makerspace
from apps.makerspaces.platform import module_enabled
from apps.machines import access as machine_access
from apps.machines.models import Machine
from apps.warranty.models import Warranty
from apps.warranty.status import (
    STATUS_ACTIVE,
    STATUS_CHOICES,
    STATUS_EXPIRED,
    STATUS_EXPIRING_SOON,
    STATUS_UNKNOWN,
    WARRANTY_EXPIRY_SOON_DAYS,
    warranty_status,
)

_VALID_STATUSES = {value for value, _ in STATUS_CHOICES}


class MakerspaceWarrantyReportView(APIView):
    permission_classes = [IsActiveStaff]
    pagination_class = InventoryPagination

    @extend_schema(
        tags=["Admin warranty"],
        summary="List warranty coverage for a makerspace",
        parameters=[
            OpenApiParameter(
                "status",
                str,
                description="Filter rows by computed warranty status.",
                enum=sorted(_VALID_STATUSES),
            ),
            OpenApiParameter(
                "missing_docs",
                bool,
                description="Only include hosts with no warranty documents or no warranty record.",
            ),
            OpenApiParameter(
                "expires_before",
                OpenApiTypes.DATE,
                description="Only include hosts with warranty expiry on or before this date.",
            ),
        ],
        responses={200: WarrantyReportRowSerializer(many=True)},
    )
    def get(self, request, makerspace_id, *args, **kwargs):
        makerspace = get_object_or_404(
            rbac.scope_by_makerspace(
                request.user,
                Makerspace.objects.filter(archived_at__isnull=True),
                "id",
            ),
            pk=makerspace_id,
        )
        query = WarrantyReportQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        filters = query.validated_data
        today = timezone.localdate()

        asset_qs = _asset_hosts(request.user, makerspace, today, filters)
        machine_qs = _machine_hosts(request.user, makerspace, today, filters)
        host_querysets = (asset_qs, machine_qs)
        host_counts = tuple(qs.count() for qs in host_querysets)
        total_count = sum(host_counts)

        paginator = self.pagination_class()
        page_size = paginator.get_page_size(request) or total_count or 1
        page_number = _page_number(request, total_count, page_size, paginator.page_query_param)
        offset = (page_number - 1) * page_size
        rows = _page_rows(host_querysets, host_counts, offset, page_size, today)
        serializer = WarrantyReportRowSerializer(rows, many=True)
        return Response(
            {
                "count": total_count,
                "next": _page_link(
                    request, page_number + 1, page_number * page_size < total_count
                ),
                "previous": _page_link(request, page_number - 1, page_number > 1),
                "results": serializer.data,
            }
        )


def _asset_hosts(user, makerspace, today, filters):
    makerspace_id = makerspace.id
    if not (
        rbac.can(user, rbac.Action.EDIT_INVENTORY, makerspace_id)
        and module_enabled(makerspace, "staff_admin")
    ):
        return InventoryAsset.objects.none()
    qs = rbac.scope_by_action(
        user,
        rbac.Action.EDIT_INVENTORY,
        InventoryAsset.objects.select_related("warranty"),
    ).filter(makerspace_id=makerspace_id)
    qs = _apply_host_filters(qs, today, filters)
    return qs.order_by(Lower("asset_tag"), "asset_tag", "id")



def _machine_hosts(user, makerspace, today, filters):
    if not module_enabled(makerspace, "machines"):
        return Machine.objects.none()
    qs = machine_access.scope_manageable_machines_for_actor(
        user,
        Machine.objects.select_related("warranty", "machine_type"),
    ).filter(makerspace_id=makerspace.id)
    qs = _apply_host_filters(qs, today, filters)
    return qs.order_by(Lower("name"), "name", "id")


def _apply_host_filters(qs, today, filters):
    qs = qs.annotate(document_count=Count("warranty__documents", distinct=True))
    if filters.get("missing_docs") is True:
        qs = qs.filter(Q(warranty__isnull=True) | Q(document_count=0))
    if expires_before := filters.get("expires_before"):
        qs = qs.filter(warranty__warranty_expires_on__lte=expires_before)
    if status := filters.get("status"):
        qs = _filter_by_status(qs, status, today)
    return qs


def _filter_by_status(qs, status, today):
    soon_cutoff = today + timedelta(days=WARRANTY_EXPIRY_SOON_DAYS)
    if status == STATUS_UNKNOWN:
        return qs.filter(Q(warranty__isnull=True) | Q(warranty__warranty_expires_on__isnull=True))
    if status == STATUS_EXPIRED:
        return qs.filter(warranty__warranty_expires_on__lt=today)
    if status == STATUS_EXPIRING_SOON:
        return qs.filter(
            warranty__warranty_expires_on__gte=today,
            warranty__warranty_expires_on__lte=soon_cutoff,
        )
    if status == STATUS_ACTIVE:
        return qs.filter(warranty__warranty_expires_on__gt=soon_cutoff)
    return qs


def _page_number(request, total_count, page_size, page_query_param):
    raw = request.query_params.get(page_query_param, "1")
    if raw == "last":
        return max(1, ceil(total_count / page_size))
    try:
        page_number = int(raw)
    except (TypeError, ValueError) as exc:
        raise NotFound("Invalid page.") from exc
    if page_number < 1:
        raise NotFound("Invalid page.")
    if total_count == 0 and page_number != 1:
        raise NotFound("Invalid page.")
    if total_count and (page_number - 1) * page_size >= total_count:
        raise NotFound("Invalid page.")
    return page_number


def _page_link(request, page_number, enabled):
    if not enabled:
        return None
    return replace_query_param(request.build_absolute_uri(), "page", page_number)


def _page_rows(host_querysets, host_counts, offset, page_size, today):
    rows = []
    remaining = page_size
    row_builders = (_asset_row, _machine_row)
    for queryset, count, row_builder in zip(
        host_querysets, host_counts, row_builders, strict=True
    ):
        if offset >= count:
            offset -= count
            continue
        limit = min(remaining, count - offset)
        rows.extend(
            row_builder(host, today)
            for host in queryset[offset : offset + limit]
        )
        remaining -= limit
        offset = 0
        if remaining == 0:
            break
    return rows


def _asset_row(asset, today):
    return _base_row(_host_warranty(asset), asset.document_count, today) | {
        "host_kind": "asset",
        "host_id": asset.id,
        "host_label": asset.asset_tag,
        "serial_number": asset.serial_number or None,
    }



def _machine_row(machine, today):
    return _base_row(_host_warranty(machine), machine.document_count, today) | {
        "host_kind": "machine",
        "host_id": machine.id,
        "host_label": machine.name,
        "serial_number": None,
    }


def _host_warranty(host):
    try:
        return host.warranty
    except Warranty.DoesNotExist:
        return None


def _base_row(warranty, document_count, today):
    if warranty is None:
        return {
            "vendor_name": None,
            "purchased_on": None,
            "warranty_expires_on": None,
            "status": STATUS_UNKNOWN,
            "document_count": 0,
        }
    return {
        "vendor_name": warranty.vendor_name,
        "purchased_on": warranty.purchased_on,
        "warranty_expires_on": warranty.warranty_expires_on,
        "status": warranty_status(warranty, today),
        "document_count": document_count or 0,
    }
