from drf_spectacular.utils import extend_schema, extend_schema_view
from django.db import transaction
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.admin_api.serializers_platform_updates import PlatformUpdateSettingsSerializer, UpdateRefusalSerializer
from apps.admin_api.permissions import IsActiveSuperAdmin
from apps.audit import services as audit
from apps.makerspaces.deployment_modules import updates_module_enabled
from apps.openapi_errors import errors
from apps.updates import services
from apps.updates.models import PlatformUpdateSettings
from apps.updates.errors import UpdateRefused


def _require_updates_module():
    """A deployment-global singleton is gated by any live space running updates."""
    if not updates_module_enabled():
        raise UpdateRefused("module_disabled", _MODULE_OFF)


_MODULE_OFF = "The updates module is not run by any live makerspace."


@extend_schema_view(
    get=extend_schema(
        responses={200: PlatformUpdateSettingsSerializer, **errors(401, 403), 400: UpdateRefusalSerializer}
    ),
    patch=extend_schema(
        responses={
            200: PlatformUpdateSettingsSerializer,
            **errors(401, 403), 400: UpdateRefusalSerializer,
        }
    ),
)
@extend_schema(
    tags=["Platform"],
    summary="Retrieve or update production release channel and update settings",
)
class PlatformUpdateSettingsView(generics.RetrieveUpdateAPIView):
    serializer_class = PlatformUpdateSettingsSerializer
    permission_classes = [IsActiveSuperAdmin]
    http_method_names = ["get", "patch", "head", "options"]

    def get_object(self):
        _require_updates_module()
        return PlatformUpdateSettings.load()

    def update(self, request, *args, **kwargs):
        from rest_framework.exceptions import ValidationError

        try:
            return super().update(request, *args, **kwargs)
        except ValidationError as exc:
            raise UpdateRefused("invalid_settings", "Select a stable/beta channel and a boolean automatic-update setting.") from exc

    @transaction.atomic
    def perform_update(self, serializer):
        instance = services._locked_settings()
        if "channel" in serializer.validated_data:
            services.prepare_channel_change(instance, serializer.validated_data["channel"])
        serializer.instance = instance
        instance = serializer.save()
        audit.record(
            self.request.user,
            "platform.update_settings_updated",
            target=instance,
            meta=dict(serializer.validated_data),
        )


@extend_schema(
    tags=["Platform"],
    summary="Queue the latest production release for installation",
    request=None,
    responses={
        status.HTTP_202_ACCEPTED: PlatformUpdateSettingsSerializer,
        **errors(401, 403), 400: UpdateRefusalSerializer,
    },
)
class PlatformUpdateRequestView(APIView):
    permission_classes = [IsActiveSuperAdmin]

    @transaction.atomic
    def post(self, request):
        _require_updates_module()
        instance = services.queue_update()
        # queue_update leaves a RUNNING update alone; the audit row must say the request
        # changed nothing rather than read as a second queued update.
        audit.record(
            request.user,
            "platform.update_requested",
            target=instance,
            meta={"noop": instance.status == PlatformUpdateSettings.Status.RUNNING},
        )
        return Response(
            PlatformUpdateSettingsSerializer(instance).data,
            status=status.HTTP_202_ACCEPTED,
        )
