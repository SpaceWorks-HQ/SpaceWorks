from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.apiclients.throttling import ClientTierRateThrottle
from apps.organizations.models import Organization
from apps.organizations.public_catalog import public_events_for
from apps.organizations.serializers_public import (
    PublicOrganizationEventListSerializer,
    PublicOrganizationEventSerializer,
    PublicOrganizationSerializer,
)


PUBLIC_ERRORS = {
    404: OpenApiResponse(description="Organization not found."),
    429: OpenApiResponse(description="Rate limit exceeded."),
}


def _public_organization(slug):
    return get_object_or_404(
        Organization.objects.filter(is_active=True, public_profile_enabled=True),
        slug=slug,
    )


class PublicOrganizationDetailView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [ClientTierRateThrottle]
    throttle_scope = "public_read"

    @extend_schema(
        tags=["Public organizations"],
        summary="Retrieve a public organization profile",
        auth=[],
        request=None,
        responses={200: PublicOrganizationSerializer, **PUBLIC_ERRORS},
    )
    def get(self, request, slug):
        return Response(PublicOrganizationSerializer(_public_organization(slug)).data)


class PublicOrganizationEventListView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [ClientTierRateThrottle]
    throttle_scope = "public_read"

    @extend_schema(
        tags=["Public organizations"],
        summary="List public events organized across makerspaces",
        auth=[],
        request=None,
        responses={200: PublicOrganizationEventListSerializer, **PUBLIC_ERRORS},
    )
    def get(self, request, slug):
        organization = _public_organization(slug)
        paginator = PageNumberPagination()
        page = paginator.paginate_queryset(public_events_for(organization), request, view=self)
        return paginator.get_paginated_response(
            PublicOrganizationEventSerializer(page, many=True).data
        )
