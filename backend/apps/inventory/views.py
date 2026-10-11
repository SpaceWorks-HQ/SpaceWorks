from django.db.models import Count, Q
from django.contrib.postgres.search import SearchVector
from django.http import Http404
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import serializers
from rest_framework.exceptions import NotFound
from rest_framework.generics import ListAPIView
from rest_framework.generics import RetrieveAPIView
from rest_framework.permissions import AllowAny

from apps.apiclients.throttling import ClientTierRateThrottle
from apps.inventory.search import SEARCH_CONFIG, apply_q
from apps.inventory.serializers import (
    PublicCategorySerializer,
    PublicMakerspaceSerializer,
    PublicProductSerializer,
)
from apps.makerspaces.models import Makerspace
from apps.makerspaces.lookup import get_public_makerspace
from apps.makerspaces.guards import require_module_for_servable
from apps.makerspaces.servability import servable_queryset
from apps.openapi import PUBLIC_API_AUTH_PARAMETERS


class PublicInventoryErrorSerializer(serializers.Serializer):
    detail = serializers.CharField(required=False)
    module = serializers.ListField(child=serializers.CharField(), required=False)
    code = serializers.CharField(required=False)


PUBLIC_INVENTORY_ERRORS = {
    400: OpenApiResponse(PublicInventoryErrorSerializer, description="Public inventory module is disabled."),
    401: OpenApiResponse(PublicInventoryErrorSerializer, description="Invalid authentication credentials."),
    403: OpenApiResponse(PublicInventoryErrorSerializer, description="Public API client is not authorized."),
    404: OpenApiResponse(PublicInventoryErrorSerializer, description="Item or public makerspace not found, or hidden by edition."),
    429: OpenApiResponse(PublicInventoryErrorSerializer, description="Public read rate limit exceeded."),
}


@extend_schema(
    tags=["Public inventory"],
    summary="List public makerspaces",
    description="List makerspaces that have public inventory enabled.",
    parameters=PUBLIC_API_AUTH_PARAMETERS,
    responses=PublicMakerspaceSerializer(many=True),
)
class PublicMakerspaceListView(ListAPIView):
    permission_classes = [AllowAny]
    throttle_classes = [ClientTierRateThrottle]
    throttle_scope = "public_read"
    serializer_class = PublicMakerspaceSerializer
    pagination_class = None

    def get_queryset(self):
        return servable_queryset(Makerspace.objects.filter(
            public_inventory_enabled=True,
        )).exclude(hidden_from_central_directory=True).order_by("name")


@extend_schema(
    tags=["Public inventory"],
    summary="List public inventory products",
    description="List public inventory products for a public makerspace.",
    parameters=[
        *PUBLIC_API_AUTH_PARAMETERS,
        OpenApiParameter(
            name="makerspace_slug",
            type=str,
            location=OpenApiParameter.PATH,
            description="Public makerspace code (for example TSEL) or slug.",
        ),
        OpenApiParameter(
            name="q",
            type=str,
            location=OpenApiParameter.QUERY,
            description="Full-text search over public name and description; supports \"phrases\" and -exclusions, tolerates typos in the name.",
        ),
        OpenApiParameter(
            name="category",
            type=str,
            location=OpenApiParameter.QUERY,
            description="Filter public products by category slug.",
        ),
        OpenApiParameter(
            name="sort",
            type=str,
            location=OpenApiParameter.QUERY,
            description="Sort public products.",
            enum=["name", "most_used", "popular"],
        ),
    ],
    responses={200: PublicProductSerializer(many=True), **PUBLIC_INVENTORY_ERRORS},
)
class PublicInventoryListView(ListAPIView):
    permission_classes = [AllowAny]
    throttle_classes = [ClientTierRateThrottle]
    throttle_scope = "public_read"
    serializer_class = PublicProductSerializer

    def get_queryset(self):
        makerspace = get_public_makerspace(self.kwargs["makerspace_slug"])
        if not makerspace.public_inventory_enabled:
            raise Http404
        require_module_for_servable(makerspace, "public_inventory")

        queryset = servable_queryset(
            makerspace.products.select_related("category").filter(
                is_public=True,
                is_archived=False,
            ),
            relation="makerspace",
        )
        query = self.request.query_params.get("q", "").strip()
        if query:
            # The staff vector includes private storage locations and tracking mode.
            # Public search must not let visitors infer either through matching rows.
            queryset = queryset.annotate(
                public_search_vector=SearchVector("name", weight="A", config=SEARCH_CONFIG)
                + SearchVector("description", weight="D", config=SEARCH_CONFIG),
            )
            queryset = apply_q(queryset, query, vector_field="public_search_vector")

        category_slug = self.request.query_params.get("category", "").strip()
        if category_slug:
            queryset = queryset.filter(category__slug=category_slug)

        sort = self.request.query_params.get("sort", "name")
        if sort == "most_used":
            return queryset.order_by("-issued_quantity", "name")
        if sort == "popular":
            from django.db.models import IntegerField, OuterRef, Subquery
            from django.db.models.functions import Coalesce

            from apps.hardware_requests.models import HardwareRequestItem

            request_count = Subquery(
                HardwareRequestItem.objects.filter(product=OuterRef("pk"))
                .values("product")
                .annotate(c=Count("*"))
                .values("c"),
                output_field=IntegerField(),
            )
            return queryset.annotate(
                request_count=Coalesce(request_count, 0),
            ).order_by("-request_count", "name")
        return queryset.order_by("name")


@extend_schema(
    tags=["Public inventory"],
    summary="List public inventory categories",
    parameters=PUBLIC_API_AUTH_PARAMETERS,
    responses={200: PublicCategorySerializer(many=True), **PUBLIC_INVENTORY_ERRORS},
)
class PublicCategoryListView(ListAPIView):
    permission_classes = [AllowAny]
    throttle_classes = [ClientTierRateThrottle]
    throttle_scope = "public_read"
    pagination_class = None
    serializer_class = PublicCategorySerializer

    def get_queryset(self):
        makerspace = get_public_makerspace(self.kwargs["makerspace_slug"])
        if not makerspace.public_inventory_enabled:
            raise Http404
        require_module_for_servable(makerspace, "public_inventory")
        return (
            makerspace.categories.annotate(
                product_count=Count(
                    "products",
                    filter=Q(products__is_public=True, products__is_archived=False),
                )
            )
            .filter(product_count__gt=0)
            .order_by("display_order", "name")
        )


@extend_schema(
    tags=["Public inventory"],
    summary="Get public inventory product detail",
    description="Read-only public catalogue detail. Private, archived and cross-space items share the same not-found response.",
    parameters=PUBLIC_API_AUTH_PARAMETERS,
    request=None,
    responses={
        200: PublicProductSerializer,
        **PUBLIC_INVENTORY_ERRORS,
    },
)
class PublicInventoryDetailView(RetrieveAPIView):
    permission_classes = [AllowAny]
    throttle_classes = [ClientTierRateThrottle]
    throttle_scope = "public_read"
    serializer_class = PublicProductSerializer

    def get_object(self):
        try:
            return super().get_object()
        except Http404 as exc:
            raise NotFound("Item not found.") from exc

    def get_queryset(self):
        makerspace = get_public_makerspace(self.kwargs["makerspace_slug"])
        if not makerspace.public_inventory_enabled:
            raise Http404
        require_module_for_servable(makerspace, "public_inventory")
        return servable_queryset(
            makerspace.products.select_related("category").filter(
                is_public=True,
                is_archived=False,
            ),
            relation="makerspace",
        ).order_by("name")
