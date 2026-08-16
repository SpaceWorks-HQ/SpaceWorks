from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import rbac
from apps.admin_api.permissions import IsActiveStaff
from apps.integrations import health as integration_health
from apps.makerspaces.servability import servable_queryset


class HealthStatusSerializer(serializers.Serializer):
    status = serializers.ChoiceField(
        choices=("ok", "warn", "error", "unknown"), required=False
    )
    detail = serializers.CharField(required=False)


class IntegrationLastFailureSerializer(serializers.Serializer):
    created_at = serializers.DateTimeField()
    subject = serializers.CharField()
    error = serializers.CharField()
    stream = serializers.CharField(allow_blank=True)


class IntegrationEmailHealthSerializer(HealthStatusSerializer):
    total = serializers.IntegerField(required=False)
    pending = serializers.IntegerField(required=False)
    sent = serializers.IntegerField(required=False)
    failed = serializers.IntegerField(required=False)
    stalled = serializers.IntegerField(required=False)
    last_failure = IntegrationLastFailureSerializer(required=False, allow_null=True)


class IntegrationDeliveriesByStreamSerializer(HealthStatusSerializer):
    hardware = serializers.DateTimeField(required=False, allow_null=True)
    printing = serializers.DateTimeField(required=False, allow_null=True)


class IntegrationConfiguredHealthSerializer(HealthStatusSerializer):
    configured = serializers.BooleanField(required=False)


class IntegrationWorkerHealthSerializer(HealthStatusSerializer):
    broker_configured = serializers.BooleanField(required=False)
    eager = serializers.BooleanField(required=False)
    last_seen = serializers.DateTimeField(required=False, allow_null=True)
    stale = serializers.BooleanField(required=False)


class IntegrationHealthSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=("ok", "warn", "error"))
    email = IntegrationEmailHealthSerializer()
    deliveries_by_stream = IntegrationDeliveriesByStreamSerializer()
    smtp = IntegrationConfiguredHealthSerializer()
    telegram = IntegrationConfiguredHealthSerializer()
    worker = IntegrationWorkerHealthSerializer()


@extend_schema(
    tags=["Integration health"],
    summary="Get makerspace integration health",
    responses={
        200: IntegrationHealthSerializer,
        403: OpenApiResponse(description="Not allowed to manage this makerspace."),
        404: OpenApiResponse(description="Makerspace not found."),
    },
)
class IntegrationHealthView(APIView):
    permission_classes = [IsActiveStaff]
    http_method_names = ["get", "head", "options"]

    def get(self, request, makerspace_id, *args, **kwargs):
        makerspace = get_object_or_404(
            rbac.scope_by_makerspace(
                request.user,
                servable_queryset(),
                makerspace_field="id",
            ),
            pk=makerspace_id,
        )
        if not rbac.can(request.user, rbac.Action.MANAGE_MAKERSPACE, makerspace.id):
            raise PermissionDenied("Not allowed to manage this makerspace.")
        serializer = IntegrationHealthSerializer(
            integration_health.build_integration_health(makerspace)
        )
        return Response(serializer.data)
