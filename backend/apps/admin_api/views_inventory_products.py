from django.shortcuts import get_object_or_404
from django.db import transaction
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import generics
from apps.admin_api.list_options import ListIdentityFilter, StableOrderingFilter
from apps.admin_api.list_options import LIST_PARAMETERS
from rest_framework.exceptions import ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView


class InventoryPagination(PageNumberPagination):
    # Opt-in larger pages (?page_size=) so pickers that need the full product list
    # (e.g. direct handout / transfers) aren't limited to the default first 24.
    page_size_query_param = "page_size"
    max_page_size = 1000

from apps.accounts import rbac
from apps.admin_api.inventory_filters import apply_inventory_list_filters
from apps.admin_api.permissions import IsActiveStaff, require_action
from apps.admin_api.serializers_inventory import (
    InventoryProductAdminCreateSerializer,
    InventoryProductAdminSerializer,
    InventoryProductAdminUpdateSerializer,
    InventoryQuantityAdjustmentSerializer,
)
from apps.audit import services as audit
from apps.hardware_requests.exceptions import ErrorSerializer
from apps.inventory import availability
from apps.inventory.models import InventoryProduct
from apps.makerspaces.guards import require_module
from apps.openapi_errors import errors


@extend_schema_view(
    post=extend_schema(request=InventoryProductAdminCreateSerializer,
                       responses={201: InventoryProductAdminSerializer,
                                  **{code: ErrorSerializer for code in (400, 401, 403, 404)}}),
    get=extend_schema(
        parameters=[
            *LIST_PARAMETERS[:2],
            OpenApiParameter(
                name="q", type=str, location=OpenApiParameter.QUERY, required=False,
                description=(
                    "Full-text search over name, storage location, tracking mode and description "
                    "(\"phrases\", -exclusions, typo-tolerant on the name), or a category name."
                ),
            ),
            OpenApiParameter(name="archived", type=str, location=OpenApiParameter.QUERY, required=False, description="`true` for archived, `false` for active; `all` or omitted includes both."),
            OpenApiParameter(name="low_stock", type=str, location=OpenApiParameter.QUERY, required=False, description="`true` to list items at or below 20% of total."),
            OpenApiParameter(name="out_of_stock", type=str, enum=["true", "false"], description="`true` for exactly zero available, matching the dashboard tile."),
        ], responses={200: InventoryProductAdminSerializer(many=True), **{code: ErrorSerializer for code in (400, 401, 403, 404)}},
    )
)
@extend_schema(tags=["Admin inventory"], summary="List or create inventory products")
class InventoryListCreateView(generics.ListCreateAPIView):
    serializer_class = InventoryProductAdminSerializer
    permission_classes = [IsActiveStaff]
    pagination_class = InventoryPagination
    filter_backends = [ListIdentityFilter, StableOrderingFilter]
    ordering_fields = ["name", "tracking_mode", "total_quantity", "available_quantity", "issued_quantity", "damaged_quantity", "lost_quantity"]
    ordering = ["name", "pk"]

    def get_serializer_class(self):
        if self.request.method == "POST":
            return InventoryProductAdminCreateSerializer
        return InventoryProductAdminSerializer

    def get_queryset(self):
        makerspace_id = self.kwargs["makerspace_id"]
        require_module(makerspace_id, "staff_admin")
        require_action(self.request.user, rbac.Action.VIEW_INVENTORY, makerspace_id)
        qs = rbac.scope_by_action(self.request.user, rbac.Action.VIEW_INVENTORY, InventoryProduct.objects.filter(makerspace_id=makerspace_id))
        return apply_inventory_list_filters(qs, self.request.query_params)

    @transaction.atomic
    def perform_create(self, serializer):
        makerspace_id = self.kwargs["makerspace_id"]
        require_module(makerspace_id, "staff_admin")
        require_action(self.request.user, rbac.Action.EDIT_INVENTORY, makerspace_id)
        _assert_box_in_makerspace(serializer.validated_data.get("box"), makerspace_id)
        _assert_category_in_makerspace(
            serializer.validated_data.get("category"), makerspace_id
        )
        instance = serializer.save(makerspace_id=makerspace_id)
        audit.record(
            self.request.user,
            "inventory.created",
            makerspace=instance.makerspace,
            target=instance,
        )


@extend_schema_view(
    get=extend_schema(request=None, responses={200: InventoryProductAdminSerializer, **errors(400, 401, 403, 404)}),
    patch=extend_schema(request=InventoryProductAdminUpdateSerializer,
                        responses={200: InventoryProductAdminUpdateSerializer, **errors(400, 401, 403, 404, 423)}),
)
@extend_schema(tags=["Admin inventory"], summary="Retrieve or update inventory product")
class InventoryDetailView(generics.RetrieveUpdateAPIView):
    serializer_class = InventoryProductAdminSerializer
    permission_classes = [IsActiveStaff]
    http_method_names = ["get", "patch", "head", "options"]

    def get_serializer_class(self):
        if self.request.method == "PATCH":
            return InventoryProductAdminUpdateSerializer
        return InventoryProductAdminSerializer

    def get_queryset(self):
        action = (
            rbac.Action.EDIT_INVENTORY
            if self.request.method == "PATCH"
            else rbac.Action.VIEW_INVENTORY
        )
        return rbac.scope_by_action(self.request.user, action, InventoryProduct.objects.select_related("makerspace", "box"))

    def get_object(self):
        product = super().get_object()
        require_module(product.makerspace, "staff_admin")
        return product

    @transaction.atomic
    def perform_update(self, serializer):
        _assert_box_in_makerspace(
            serializer.validated_data.get("box"), serializer.instance.makerspace_id
        )
        _assert_category_in_makerspace(
            serializer.validated_data.get("category"), serializer.instance.makerspace_id
        )
        instance = serializer.save()
        audit.record(
            self.request.user,
            "inventory.updated",
            makerspace=instance.makerspace,
            target=instance,
        )


class InventoryQuantityAdjustmentView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(
        tags=["Admin inventory"],
        summary="Adjust inventory quantity buckets",
        request=InventoryQuantityAdjustmentSerializer,
        responses={200: InventoryProductAdminSerializer},
    )
    def post(self, request, pk, *args, **kwargs):
        product = get_object_or_404(
            rbac.scope_by_action(
                request.user,
                rbac.Action.VIEW_INVENTORY,
                InventoryProduct.objects.select_related("makerspace"),
            ),
            pk=pk,
        )
        require_module(product.makerspace_id, "staff_admin")
        require_action(request.user, rbac.Action.EDIT_INVENTORY, product.makerspace_id)
        serializer = InventoryQuantityAdjustmentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            locked = availability.adjust_quantities(
                product,
                delta_available=data["delta_available"],
                delta_damaged=data["delta_damaged"],
                delta_lost=data["delta_lost"],
                reason=data["reason"],
                actor=request.user,
            )
        except availability.InsufficientStock as exc:
            raise ValidationError(str(exc)) from exc
        return Response(InventoryProductAdminSerializer(locked).data)


def _assert_box_in_makerspace(box, makerspace_id):
    """A product may only point at a box in its own makerspace (tenant isolation)."""
    if box is not None and box.makerspace_id != makerspace_id:
        raise ValidationError({"box": "Box belongs to a different makerspace."})


def _assert_category_in_makerspace(category, makerspace_id):
    """A product may only point at a category in its own makerspace."""
    if category is not None and category.makerspace_id != makerspace_id:
        raise ValidationError(
            {"category": "Category belongs to a different makerspace."}
        )
