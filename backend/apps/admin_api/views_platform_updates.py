from drf_spectacular.utils import extend_schema
from rest_framework import generics, serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from django.http import Http404

from apps.admin_api.permissions import IsActiveSuperAdmin
from apps.audit import services as audit
from apps.makerspaces.deployment_modules import updates_module_enabled
from apps.updates import services
from apps.updates.models import PlatformUpdateSettings


def _require_updates_module():
    """404 the in-app updater when the deployment does not run it.

    `PlatformUpdateSettings` is a pk=1 singleton for the whole box, so there is no
    makerspace to scope the module by -- see `makerspaces.deployment_modules` for why
    this reads as "does any live makerspace run it" rather than being threaded per
    tenant. 404 rather than 403: an uninstalled surface should not exist, and the
    console prunes the panel the same way a tombstoned app's sidebar entry is dropped
    rather than permission-hidden.
    """
    if not updates_module_enabled():
        raise Http404


class PlatformUpdateSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = PlatformUpdateSettings
        fields = (
            "automatic_updates_enabled",
            "status",
            "current_version",
            "available_version",
            "target_version",
            "update_requested_at",
            "last_checked_at",
            "last_updated_at",
            "last_backup_at",
            "last_backup_name",
            "last_error",
            "updated_at",
        )
        read_only_fields = (
            "status",
            "current_version",
            "available_version",
            "target_version",
            "update_requested_at",
            "last_checked_at",
            "last_updated_at",
            "last_backup_at",
            "last_backup_name",
            "last_error",
            "updated_at",
        )


@extend_schema(
    tags=["Platform"],
    summary="Retrieve or update automatic production update settings",
)
class PlatformUpdateSettingsView(generics.RetrieveUpdateAPIView):
    serializer_class = PlatformUpdateSettingsSerializer
    permission_classes = [IsActiveSuperAdmin]
    http_method_names = ["get", "patch", "head", "options"]

    def get_object(self):
        _require_updates_module()
        return PlatformUpdateSettings.load()

    def perform_update(self, serializer):
        instance = serializer.save()
        audit.record(
            self.request.user,
            "platform.update_settings_updated",
            target=instance,
            meta={
                "automatic_updates_enabled": instance.automatic_updates_enabled,
            },
        )


@extend_schema(
    tags=["Platform"],
    summary="Queue the latest production release for installation",
    request=None,
    responses={status.HTTP_202_ACCEPTED: PlatformUpdateSettingsSerializer},
)
class PlatformUpdateRequestView(APIView):
    permission_classes = [IsActiveSuperAdmin]

    def post(self, request):
        _require_updates_module()
        instance = services.queue_update()
        audit.record(
            request.user,
            "platform.update_requested",
            target=instance,
        )
        return Response(
            PlatformUpdateSettingsSerializer(instance).data,
            status=status.HTTP_202_ACCEPTED,
        )
