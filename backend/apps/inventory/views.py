from django.db.models import Count, Q
from django.http import Http404
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.generics import ListAPIView
from rest_framework.generics import RetrieveAPIView
from rest_framework.permissions import AllowAny

from apps.apiclients.throttling import ClientTierRateThrottle
from apps.inventory.serializers import (
    PublicCategorySerializer,
    PublicMakerspaceSerializer,
    PublicProductSerializer,
)
from apps.makerspaces.models import Makerspace
from apps.makerspaces.lookup import get_public_makerspace
from apps.makerspaces.platform import module_enabled
from apps.makerspaces.servability import servable_queryset
from apps.openapi import PUBLISHABLE_KEY_PARAMETER


@extend_schema(
    tags=["Public inventory"],
    summary="List public makerspaces",
    description="List makerspaces that have public inventory enabled.",
    parameters=[PUBLISHABLE_KEY_PARAMETER],
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
        PUBLISHABLE_KEY_PARAMETER,
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
            description="Search public products by name or description.",
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
    responses=PublicProductSerializer(many=True),
)
class PublicInventoryListView(ListAPIView):
    permission_classes = [AllowAny]
    throttle_classes = [ClientTierRateThrottle]
    throttle_scope = "public_read"
    serializer_class = PublicProductSerializer

    def get_queryset(self):
        makerspace = get_public_makerspace(self.kwargs["makerspace_slug"])
        if not makerspace.public_inventory_enabled or not module_enabled(
            makerspace,
            "public_inventory",
        ):
            raise Http404

        queryset = servable_queryset(
            makerspace.products.select_related("category").filter(
                is_public=True,
                is_archived=False,
            ),
            relation="makerspace",
        )
        query = self.request.query_params.get("q", "").strip()
        if query:
            queryset = queryset.filter(
                Q(name__icontains=query) | Q(description__icontains=query)
            )

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
    parameters=[PUBLISHABLE_KEY_PARAMETER],
    responses=PublicCategorySerializer(many=True),
)
class PublicCategoryListView(ListAPIView):
    permission_classes = [AllowAny]
    throttle_classes = [ClientTierRateThrottle]
    throttle_scope = "public_read"
    pagination_class = None
    serializer_class = PublicCategorySerializer

    def get_queryset(self):
        makerspace = get_public_makerspace(self.kwargs["makerspace_slug"])
        if not makerspace.public_inventory_enabled or not module_enabled(
            makerspace,
            "public_inventory",
        ):
            raise Http404
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
    parameters=[PUBLISHABLE_KEY_PARAMETER],
    responses=PublicProductSerializer,
)
class PublicInventoryDetailView(RetrieveAPIView):
    permission_classes = [AllowAny]
    throttle_classes = [ClientTierRateThrottle]
    throttle_scope = "public_read"
    serializer_class = PublicProductSerializer

    def get_queryset(self):
        makerspace = get_public_makerspace(self.kwargs["makerspace_slug"])
        if not makerspace.public_inventory_enabled or not module_enabled(
            makerspace,
            "public_inventory",
        ):
            raise Http404
        return servable_queryset(
            makerspace.products.select_related("category").filter(
                is_public=True,
                is_archived=False,
            ),
            relation="makerspace",
        ).order_by("name")
