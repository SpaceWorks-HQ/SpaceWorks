from rest_framework import serializers

from apps.admin_api.serializers_makerspace_aux import (
    MakerspaceDisabledRowSerializer,
    MakerspaceSwitcherSerializer,
    ReturnPolicySerializer,
)
from apps.admin_api.serializers_makerspace_mutations import (
    MakerspaceMutationMixin,
)
from apps.admin_api.serializers_makerspace_validation import (
    MakerspaceValidationMixin,
)
from apps.makerspaces.models import Makerspace


class MakerspaceSerializer(
    MakerspaceValidationMixin,
    MakerspaceMutationMixin,
    serializers.ModelSerializer,
):
    resource_limit_overrides = serializers.JSONField(required=False)
    frontend_domain = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        max_length=255,
    )
    telegram_bot_token = serializers.CharField(
        write_only=True,
        required=False,
        allow_blank=True,
    )
    smtp_password = serializers.CharField(
        write_only=True,
        required=False,
        allow_blank=True,
    )
    telegram_bot_token_set = serializers.SerializerMethodField()
    smtp_password_set = serializers.SerializerMethodField()
    slack_webhook_url = serializers.CharField(
        write_only=True, required=False, allow_blank=True, max_length=2048
    )
    mattermost_webhook_url = serializers.CharField(
        write_only=True, required=False, allow_blank=True, max_length=2048
    )
    discord_webhook_url = serializers.CharField(
        write_only=True, required=False, allow_blank=True, max_length=2048
    )
    slack_webhook_url_set = serializers.SerializerMethodField()
    mattermost_webhook_url_set = serializers.SerializerMethodField()
    discord_webhook_url_set = serializers.SerializerMethodField()
    logo_url = serializers.SerializerMethodField()
    cover_image_url = serializers.SerializerMethodField()
    domain_verification_record = serializers.SerializerMethodField()
    platform_hosting = serializers.SerializerMethodField()
    is_platform_subdomain = serializers.SerializerMethodField()
    archive_custody_state = serializers.SerializerMethodField()
    public_display_name = serializers.CharField(
        write_only=True,
        required=False,
        allow_blank=True,
        max_length=200,
        trim_whitespace=True,
    )
    enabled_modules = serializers.SerializerMethodField()
    unavailable_apps = serializers.SerializerMethodField()

    class Meta:
        model = Makerspace
        fields = [
            "id",
            "name",
            "public_code",
            "slug",
            "location",
            "map_url",
            "geofence_latitude",
            "geofence_longitude",
            "geofence_radius_m",
            "geofence_enabled",
            "public_inventory_enabled",
            "public_stats_enabled",
            "public_stats_show_holder_names",
            "public_print_status_lookup_policy",
            "membership_policy",
            "membership_dues_amount",
            "referrals_enabled",
            "filament_low_stock_threshold_grams",
            "superadmin_access_enabled",
            "archive_custody_state",
            "staff_notifications_enabled",
            "booking_requester_notifications_enabled",
            "logo_key",
            "logo_url",
            "cover_image_key",
            "cover_image_url",
            "frontend_domain",
            "frontend_domain_status",
            "domain_verified_at",
            "domain_verification_token",
            "domain_verification_record",
            "platform_hosting",
            "is_platform_subdomain",
            "hidden_from_central_directory",
            "public_api_key",
            "cors_allowed_origins",
            "enabled_modules",
            "unavailable_apps",
            "resource_limit_overrides",
            "enabled_features",
            "theme_config",
            "branding_config",
            "public_display_name",
            "telegram_group_chat_id",
            "telegram_bot_token",
            "telegram_bot_token_set",
            "smtp_host",
            "smtp_port",
            "smtp_username",
            "smtp_password",
            "smtp_password_set",
            "smtp_use_tls",
            "smtp_use_ssl",
            "smtp_from_email",
            "slack_webhook_url",
            "slack_webhook_url_set",
            "mattermost_webhook_url",
            "mattermost_webhook_url_set",
            "discord_webhook_url",
            "discord_webhook_url_set",
            "default_loan_days",
            "presence_preset_minutes",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "public_api_key",
            "logo_key",
            "logo_url",
            "cover_image_key",
            "cover_image_url",
            "frontend_domain_status",
            "domain_verified_at",
            "domain_verification_token",
            "domain_verification_record",
            "platform_hosting",
            "is_platform_subdomain",
            "archive_custody_state",
            "telegram_bot_token_set",
            "smtp_password_set",
            "slack_webhook_url_set",
            "mattermost_webhook_url_set",
            "discord_webhook_url_set",
            "branding_config",
            "enabled_modules",
            "unavailable_apps",
            "created_at",
            "updated_at",
        ]
