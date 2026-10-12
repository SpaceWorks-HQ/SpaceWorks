from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.admin_api.permissions import IsActiveSuperAdmin
from apps.openapi_errors import errors
from apps.organizations.models import Organization, OrganizationMakerspace
from apps.organizations.services_console import change_link, visible_spaces


class OrganizationCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Organization
        fields = ("name", "slug", "description", "website", "public_profile_enabled")


class OrganizationLinkWriteSerializer(serializers.Serializer):
    makerspace_id = serializers.IntegerField(min_value=1)
    relationship = serializers.ChoiceField(choices=OrganizationMakerspace.Relationship.choices)


class OrganizationLinkSerializer(serializers.ModelSerializer):
    makerspace_id = serializers.IntegerField(read_only=True)
    makerspace_name = serializers.CharField(source="makerspace.name", read_only=True)

    class Meta:
        model = OrganizationMakerspace
        fields = ("id", "makerspace_id", "makerspace_name", "relationship")


class OrganizationLinkPageSerializer(serializers.Serializer):
    count = serializers.IntegerField()
    next = serializers.URLField(allow_null=True)
    previous = serializers.URLField(allow_null=True)
    results = OrganizationLinkSerializer(many=True)


def console_errors(*codes):
    # DRF validation may return field lists; auth/gate/conflict errors use detail.
    schema = {"type": "object", "additionalProperties": True, "properties": {
        "detail": {"type": "string"}, "code": {"type": "string"},
        "purpose": {"type": "string"},
    }}
    return {code: OpenApiResponse(response=schema, description=entry.description)
            for code, entry in errors(*codes).items()}


WRITE_ERRORS = console_errors(400, 401, 403, 404, 409, 423, 503)


class OrganizationLinksView(APIView):
    permission_classes = [IsActiveSuperAdmin]

    @extend_schema(tags=["Admin organizations"], request=None,
                   responses={200: OrganizationLinkPageSerializer, **console_errors(401, 403, 404)})
    def get(self, request, pk):
        get_object_or_404(Organization, pk=pk)
        rows = OrganizationMakerspace.objects.filter(organization_id=pk, makerspace__in=visible_spaces(request.user))
        pager = PageNumberPagination()
        page = pager.paginate_queryset(rows.select_related("makerspace").order_by("makerspace__name", "id"), request, view=self)
        return pager.get_paginated_response(OrganizationLinkSerializer(page, many=True).data)

    @extend_schema(tags=["Admin organizations"], request=OrganizationLinkWriteSerializer,
                   responses={200: OrganizationLinkSerializer, **WRITE_ERRORS})
    def post(self, request, pk):
        serializer = OrganizationLinkWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        row = change_link(request.user, pk, **serializer.validated_data)
        return Response(OrganizationLinkSerializer(row).data)


class OrganizationLinkDeleteView(APIView):
    permission_classes = [IsActiveSuperAdmin]

    @extend_schema(tags=["Admin organizations"], request=None, responses={204: None, **WRITE_ERRORS})
    def delete(self, request, pk, makerspace_id):
        change_link(request.user, pk, makerspace_id)
        return Response(status=204)
