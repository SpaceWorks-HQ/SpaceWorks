"""Own training history, without staff notes or other members' identities."""

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from apps.accounts import rbac
from apps.makerspaces.guards import require_module
from apps.makerspaces.member_activity_service import active_membership
from apps.openapi_errors import errors
from .models import CertificationGrant


class MemberCertificationSerializer(serializers.ModelSerializer):
    name = serializers.CharField(source="certification_type.name")
    machine_type_name = serializers.CharField(source="certification_type.machine_type.name")
    type_active = serializers.BooleanField(source="certification_type.is_active")
    is_live = serializers.SerializerMethodField()

    class Meta:
        model = CertificationGrant
        fields = ["id", "name", "machine_type_name", "type_active", "granted_at", "expires_at", "revoked_at", "is_live"]

    def get_is_live(self, obj) -> bool:
        return obj.certification_type.is_active and obj.is_active()


class MemberCertificationPageSerializer(serializers.Serializer):
    count = serializers.IntegerField()
    next = serializers.CharField(allow_null=True)
    previous = serializers.CharField(allow_null=True)
    results = MemberCertificationSerializer(many=True)


class MemberCertificationsView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["Member certifications"], summary="List your own certification history",
                   parameters=[OpenApiParameter("page", int, OpenApiParameter.QUERY, description="Page number (24 rows per page).")],
                   request=None, responses={200: MemberCertificationPageSerializer, **errors(400, 401, 403, 404)})
    def get(self, request, makerspace_id):
        membership = active_membership(request.user, makerspace_id)
        if membership is None:
            raise PermissionDenied()
        require_module(membership.makerspace, "machines")
        rows = rbac.scope_by_makerspace(
            request.user, CertificationGrant.objects.select_related("certification_type__machine_type"),
            makerspace_field="certification_type__makerspace_id",
        ).filter(membership=membership, certification_type__makerspace=membership.makerspace).order_by("-granted_at", "-pk")
        paginator = PageNumberPagination()
        paginator.page_size = 24
        page = paginator.paginate_queryset(rows, request, view=self)
        return paginator.get_paginated_response(MemberCertificationSerializer(page, many=True).data)
