"""Minimal active-member picker for type-authorized trainers, without contact PII."""

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers
from rest_framework.pagination import PageNumberPagination
from rest_framework.views import APIView

from apps.accounts import rbac
from apps.admin_api.permissions import IsActiveStaff
from apps.makerspaces.models import MakerspaceMembership
from apps.openapi_errors import errors
from .views_certification_types import _resolved_type


class CertificationMemberSerializer(serializers.ModelSerializer):
    name = serializers.SerializerMethodField()

    class Meta:
        model = MakerspaceMembership
        fields = ["id", "name"]

    def get_name(self, obj) -> str:
        return obj.user.display_name or obj.user.get_full_name() or obj.user.username


class CertificationMemberPageSerializer(serializers.Serializer):
    count = serializers.IntegerField()
    next = serializers.CharField(allow_null=True)
    previous = serializers.CharField(allow_null=True)
    results = CertificationMemberSerializer(many=True)


class CertificationMembersView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(tags=["Admin machines"], summary="List active members eligible for training grants",
                   parameters=[OpenApiParameter("page", int, OpenApiParameter.QUERY, description="Page number (24 rows per page).")],
                   request=None, responses={200: CertificationMemberPageSerializer, **errors(400, 401, 403, 404)})
    def get(self, request, pk):
        row = _resolved_type(request.user, pk)
        rows = rbac.scope_by_makerspace(request.user, MakerspaceMembership.objects.select_related("user")).filter(
            makerspace_id=row.makerspace_id, status="active", user__is_active=True,
            user__access_status="active",
        ).order_by("user__display_name", "user__username", "pk")
        paginator = PageNumberPagination()
        paginator.page_size = 24
        page = paginator.paginate_queryset(rows, request, view=self)
        return paginator.get_paginated_response(CertificationMemberSerializer(page, many=True).data)
