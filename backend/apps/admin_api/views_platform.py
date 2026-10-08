from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import generics, serializers

from apps.admin_api.permissions import IsActiveSuperAdmin
from apps.audit import services as audit
from apps.integrations.models import PlatformEmailSettings
from apps.integrations.smtp_validation import validate_smtp_settings
from apps.openapi_errors import errors


class PlatformEmailSettingsSerializer(serializers.ModelSerializer):
    smtp_password = serializers.CharField(
        write_only=True,
        required=False,
        allow_blank=True,
    )
    smtp_password_set = serializers.SerializerMethodField()

    class Meta:
        model = PlatformEmailSettings
        fields = (
            "id",
            "smtp_host",
            "smtp_port",
            "smtp_username",
            "smtp_password",
            "smtp_password_set",
            "smtp_use_tls",
            "smtp_use_ssl",
            "from_email",
            "updated_at",
        )
        read_only_fields = ("id", "smtp_password_set", "updated_at")

    def get_smtp_password_set(self, obj) -> bool:
        return bool(obj.smtp_password)

    def validate(self, attrs):
        validate_smtp_settings(attrs, self.instance)
        return attrs

    def update(self, instance, validated_data):
        smtp_password = validated_data.pop("smtp_password", None)
        if smtp_password is not None:
            instance.set_smtp_password(smtp_password)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        return instance


@extend_schema_view(
    get=extend_schema(responses={200: PlatformEmailSettingsSerializer, **errors(401, 403)}),
    patch=extend_schema(responses={200: PlatformEmailSettingsSerializer, **errors(400, 401, 403)}),
)
@extend_schema(
    tags=["Platform"],
    summary="Retrieve or update platform email settings",
)
class PlatformEmailSettingsView(generics.RetrieveUpdateAPIView):
    serializer_class = PlatformEmailSettingsSerializer
    permission_classes = [IsActiveSuperAdmin]
    http_method_names = ["get", "patch", "head", "options"]

    def get_object(self):
        return PlatformEmailSettings.load()

    def perform_update(self, serializer):
        instance = serializer.save()
        audit.record(
            self.request.user,
            "platform.email_settings_updated",
            target=instance,
        )

