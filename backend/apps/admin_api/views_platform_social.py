from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import generics, serializers

from apps.accounts.models_social import PlatformSocialAuthSettings
from apps.admin_api.permissions import IsActiveSuperAdmin
from apps.audit import services as audit
from apps.openapi_errors import errors


class PlatformSocialAuthSettingsSerializer(serializers.ModelSerializer):
    apple_private_key = serializers.CharField(
        write_only=True, required=False, allow_blank=True
    )
    apple_private_key_set = serializers.BooleanField(read_only=True)

    class Meta:
        model = PlatformSocialAuthSettings
        fields = (
            "google_web_client_id",
            "google_ios_client_id",
            "google_android_client_id",
            "apple_service_id",
            "apple_native_app_ids",
            "apple_team_id",
            "apple_key_id",
            "apple_private_key",
            "apple_private_key_set",
            "updated_at",
        )
        read_only_fields = ("apple_private_key_set", "updated_at")

    def validate_apple_native_app_ids(self, value):
        if not isinstance(value, list) or len(value) > 10:
            raise serializers.ValidationError("Enter at most ten Apple app audiences.")
        cleaned = []
        for item in value:
            if not isinstance(item, str) or not 3 <= len(item.strip()) <= 255:
                raise serializers.ValidationError("Enter valid Apple app audiences.")
            cleaned.append(item.strip())
        return list(dict.fromkeys(cleaned))

    def validate(self, attrs):
        # The same refusal the /control/ form applies (`social_lockout`): clearing a
        # provider through the API must not strand accounts the form would protect.
        from apps.accounts.social_lockout import GOOGLE_FIELDS, disabling_lockout_message

        stored = self.instance
        incoming = PlatformSocialAuthSettings(
            **{
                field: attrs.get(field, getattr(stored, field, "") if stored else "")
                for field in (*GOOGLE_FIELDS, "apple_service_id", "apple_native_app_ids")
            }
        )
        message = disabling_lockout_message(stored, incoming)
        if message:
            raise serializers.ValidationError(message)
        return attrs

    def update(self, instance, validated_data):
        private_key = validated_data.pop("apple_private_key", None)
        if private_key is not None:
            instance.set_apple_private_key(private_key)
        for field, value in validated_data.items():
            setattr(instance, field, value)
        instance.save()
        return instance


@extend_schema_view(
    get=extend_schema(responses={200: PlatformSocialAuthSettingsSerializer, **errors(401, 403)}),
    patch=extend_schema(responses={200: PlatformSocialAuthSettingsSerializer, **errors(400, 401, 403)}),
)
@extend_schema(
    tags=["Platform"], summary="Retrieve or update platform social auth settings"
)
class PlatformSocialAuthSettingsView(generics.RetrieveUpdateAPIView):
    serializer_class = PlatformSocialAuthSettingsSerializer
    permission_classes = [IsActiveSuperAdmin]
    http_method_names = ["get", "patch", "head", "options"]

    def get_object(self):
        return PlatformSocialAuthSettings.load()

    def perform_update(self, serializer):
        instance = serializer.save()
        from apps.accounts.social_csp import clear_social_csp_cache

        clear_social_csp_cache()
        audit.record(
            self.request.user,
            "platform.social_auth_settings_updated",
            target=instance,
            meta={
                "google_web_configured": bool(instance.google_web_client_id),
                "apple_web_configured": bool(instance.apple_service_id),
                "apple_private_key_set": instance.apple_private_key_set,
            },
        )
