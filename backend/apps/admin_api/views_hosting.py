from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import rbac
from apps.admin_api.permissions import IsActiveSuperAdmin
from apps.admin_api.serializers_makerspaces import MakerspaceSerializer
from apps.makerspaces import hosting
from apps.makerspaces.provisioning import provision_subdomain
from apps.makerspaces.servability import servable_queryset


class ProvisionSubdomainRequestSerializer(serializers.Serializer):
    label = serializers.CharField(max_length=63, trim_whitespace=True)


class ProvisionSubdomainValidationErrorSerializer(serializers.Serializer):
    label = serializers.ListField(child=serializers.CharField())


class HostingErrorSerializer(serializers.Serializer):
    detail = serializers.CharField()


def _deny_tls():
    return HttpResponseForbidden(b"Forbidden")


@extend_schema(
    tags=["Internal"],
    summary="Check whether on-demand TLS may be issued for a domain",
    parameters=[
        OpenApiParameter(
            name="domain",
            type=str,
            location=OpenApiParameter.QUERY,
            required=True,
            description="Canonical hostname requested for on-demand TLS issuance.",
        )
    ],
    responses={
        200: OpenApiResponse(description="TLS issuance is allowed."),
        403: OpenApiResponse(description="TLS issuance is denied."),
    },
    auth=[],
)
class TlsCheckView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    http_method_names = ["get", "options"]

    def get(self, request, *args, **kwargs):
        try:
            domain = hosting.canonical_host(request.query_params.get("domain", ""))
            if domain is None:
                return _deny_tls()
            suffix = str(settings.PLATFORM_DOMAIN_SUFFIX or "").strip().lower()
            if suffix and domain.endswith(suffix):
                return _deny_tls()
            if domain not in hosting.verified_frontend_domains():
                return _deny_tls()
            return HttpResponse(b"OK")
        except Exception:
            return _deny_tls()


@extend_schema(
    tags=["Admin makerspaces"],
    summary="Provision a platform subdomain for a makerspace",
    request=ProvisionSubdomainRequestSerializer,
    responses={
        200: MakerspaceSerializer,
        400: OpenApiResponse(
            response=ProvisionSubdomainValidationErrorSerializer,
            description="Invalid or unavailable platform subdomain label.",
        ),
        403: OpenApiResponse(
            response=HostingErrorSerializer,
            description="Active superadmin access is required.",
        ),
        404: OpenApiResponse(
            response=HostingErrorSerializer,
            description="Makerspace not found.",
        ),
    },
)
class MakerspaceProvisionSubdomainView(APIView):
    permission_classes = [IsActiveSuperAdmin]
    http_method_names = ["post", "options"]

    def post(self, request, makerspace_id, *args, **kwargs):
        serializer = ProvisionSubdomainRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        makerspace = get_object_or_404(
            rbac.scope_by_action(
                request.user,
                rbac.Action.MANAGE_MAKERSPACE,
                servable_queryset(),
                field="id",
            ),
            pk=makerspace_id,
        )
        try:
            provisioned = provision_subdomain(
                makerspace,
                serializer.validated_data["label"],
                request.user,
            )
        except DjangoValidationError as exc:
            raise ValidationError({"label": exc.messages}) from exc
        return Response(MakerspaceSerializer(provisioned, context={"request": request}).data)
