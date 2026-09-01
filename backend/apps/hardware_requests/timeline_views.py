from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import rbac
from apps.admin_api.permissions import IsActiveStaff
from apps.hardware_requests.serializers_timeline import (
    InventoryChainOfCustodyResponseSerializer,
    RequestTimelineResponseSerializer,
)
from apps.hardware_requests.timeline_service import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    build_inventory_chain_of_custody,
    build_request_timeline,
)
from apps.hardware_requests.view_helpers import ACTION_ERROR_RESPONSES, request_queryset
from apps.inventory.models import InventoryProduct

LIMIT_PARAMETER = OpenApiParameter(
    name="limit",
    type=int,
    location=OpenApiParameter.QUERY,
    required=False,
    description=f"Maximum history events to return. Defaults to {DEFAULT_LIMIT}; capped at {MAX_LIMIT}.",
)


class RequestTimelineView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(
        tags=["Admin requests"],
        summary="Read-only immutable timeline for one hardware request",
        parameters=[LIMIT_PARAMETER],
        responses={200: RequestTimelineResponseSerializer, **ACTION_ERROR_RESPONSES},
    )
    def get(self, request, pk, *args, **kwargs):
        _require_any_audit_scope(request.user)
        scoped = rbac.scope_by_action(
            request.user,
            rbac.Action.VIEW_AUDIT,
            request_queryset().select_related(
                "requester",
                "accepted_by",
                "assigned_box",
                "issued_by",
                "issue_evidence",
            ),
        )
        scoped = rbac.hide_from_superadmin(request.user, scoped, "makerspace_id")
        hardware_request = get_object_or_404(scoped, pk=pk)
        data = build_request_timeline(hardware_request, limit=_limit(request))
        return Response(RequestTimelineResponseSerializer(data).data)


class InventoryChainOfCustodyView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(
        tags=["Admin inventory"],
        summary="Read-only chain of custody for one inventory item",
        parameters=[LIMIT_PARAMETER],
        responses={200: InventoryChainOfCustodyResponseSerializer, **ACTION_ERROR_RESPONSES},
    )
    def get(self, request, pk, *args, **kwargs):
        _require_any_audit_scope(request.user)
        scoped = rbac.scope_by_action(
            request.user,
            rbac.Action.VIEW_AUDIT,
            InventoryProduct.objects.all(),
        )
        scoped = rbac.hide_from_superadmin(request.user, scoped, "makerspace_id")
        product = get_object_or_404(scoped, pk=pk)
        data = build_inventory_chain_of_custody(product, limit=_limit(request))
        return Response(InventoryChainOfCustodyResponseSerializer(data).data)


def _require_any_audit_scope(user):
    if not rbac.makerspaces_for_action(user, rbac.Action.VIEW_AUDIT):
        raise PermissionDenied()


def _limit(request):
    raw = request.query_params.get("limit", DEFAULT_LIMIT)
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValidationError({"limit": "Limit must be an integer."}) from exc
    if value < 1:
        raise ValidationError({"limit": "Limit must be at least 1."})
    return min(value, MAX_LIMIT)
