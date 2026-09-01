from drf_spectacular.utils import (
    OpenApiParameter,
    OpenApiResponse,
    extend_schema,
    inline_serializer,
)
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.makerspaces.models import Makerspace
from apps.makerspaces.platform import bootstrap_payload, resolve_frontend

TenantBootstrapSerializer = inline_serializer(
    name="TenantBootstrap",
    fields={
        "makerspace": inline_serializer(
            name="TenantBootstrapMakerspace",
            fields={
                "id": serializers.IntegerField(),
                "name": serializers.CharField(),
                "slug": serializers.CharField(),
                "public_code": serializers.CharField(),
                "location": serializers.CharField(allow_blank=True),
                "map_url": serializers.URLField(allow_blank=True),
                "geofence_enabled": serializers.BooleanField(required=False),
                "logo_url": serializers.CharField(allow_blank=True, allow_null=True),
                "cover_image_url": serializers.CharField(
                    allow_blank=True, allow_null=True
                ),
                "public_stats_enabled": serializers.BooleanField(),
                "membership_policy": serializers.ChoiceField(
                    choices=Makerspace.MembershipPolicy.choices
                ),
                # `required=False` for the same reason as `geofence_enabled`: the key is
                # emitted ONLY when the makerspace opted into account-less requests, so
                # every other deployment keeps a byte-for-byte identical payload. Absent
                # means an account is required.
                "request_access": serializers.ChoiceField(
                    choices=[("anyone", "anyone")], required=False
                ),
            },
        ),
        "frontend": inline_serializer(
            name="TenantBootstrapFrontend",
            fields={
                "type": serializers.CharField(),
                "hostname": serializers.CharField(allow_blank=True),
                "allowed_origins": serializers.ListField(
                    child=serializers.CharField()
                ),
            },
        ),
        "modules": serializers.ListField(child=serializers.CharField()),
        "features": serializers.ListField(child=serializers.CharField()),
        "workflows": serializers.ListField(child=serializers.CharField()),
        "theme": serializers.JSONField(),
        "branding": serializers.JSONField(),
        "email_enabled": serializers.BooleanField(),
        "public_api": inline_serializer(
            name="TenantBootstrapPublicApi",
            fields={
                "base_url": serializers.CharField(),
                "publishable_key": serializers.CharField(),
                "inventory_path": serializers.CharField(),
            },
        ),
    },
)


class BootstrapView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(
        tags=["Tenant bootstrap"],
        summary="Resolve tenant and frontend-safe configuration",
        parameters=[
            OpenApiParameter("tenant", str, OpenApiParameter.QUERY),
            OpenApiParameter("slug", str, OpenApiParameter.QUERY),
        ],
        responses={
            200: OpenApiResponse(
                response=TenantBootstrapSerializer,
                description="Frontend-safe tenant bootstrap payload.",
            ),
            404: OpenApiResponse(description="No active tenant frontend matched."),
        },
    )
    def get(self, request, *args, **kwargs):
        makerspace = resolve_frontend(
            tenant=request.query_params.get("tenant"),
            slug=request.query_params.get("slug"),
            origin=request.headers.get("Origin"),
            host=request.get_host(),
        )
        if makerspace is None:
            return Response(
                {"detail": "No active tenant frontend matched."},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(bootstrap_payload(makerspace))
