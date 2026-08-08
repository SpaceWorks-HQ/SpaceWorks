import re

from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.utils import timezone
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied

from apps.accounts.models import User
from apps.inventory import public_image_storage
from apps.integrations.email import platform_email_configured
from apps.integrations.smtp_validation import validate_smtp_settings
from apps.integrations.webhook_validation import validate_webhook_url
from apps.makerspaces import domain_verification, limits
from apps.makerspaces.hosting import canonical_host
from apps.makerspaces.capabilities import validate_capabilities
from apps.makerspaces.platform import available_modules
from apps.makerspaces.models import (
    Makerspace,
    default_branding_config,
    normalize_frontend_domain,
)
from apps.makerspaces.validators import validate_google_maps_url, validate_presence_presets
from apps.admin_api.serializers_makerspace_aux import (
    MakerspaceDisabledRowSerializer,
    MakerspaceSwitcherSerializer,
    ReturnPolicySerializer,
)

# Bare hostname (DNS labels); allows "localhost" and "alpha-lab.example.com",
# rejects schemes, paths, ports, spaces, and empty labels.
_HOSTNAME_RE = re.compile(
    r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)*$"
)


class MakerspaceSerializer(serializers.ModelSerializer):
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
    slack_webhook_url_set = serializers.SerializerMethodField()
    mattermost_webhook_url_set = serializers.SerializerMethodField()
    logo_url = serializers.SerializerMethodField()
    cover_image_url = serializers.SerializerMethodField()
    domain_verification_record = serializers.SerializerMethodField()
    platform_hosting = serializers.SerializerMethodField()
    is_platform_subdomain = serializers.SerializerMethodField()
    # Optional public-name override stored under branding_config["display_name"].
    # Blank => public pages fall back to the registered makerspace name. Written
    # through this dedicated, validated field (not the whole branding_config blob)
    # so we only touch the one key under the row lock and never clobber the rest.
    public_display_name = serializers.CharField(
        write_only=True,
        required=False,
        allow_blank=True,
        max_length=200,
        trim_whitespace=True,
    )
    enabled_modules = serializers.SerializerMethodField()

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
            "public_print_status_lookup_policy",
            "membership_policy",
            "membership_dues_amount",
            "referrals_enabled",
            "filament_low_stock_threshold_grams",
            "superadmin_access_enabled",
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
            "telegram_bot_token_set",
            "smtp_password_set",
            "slack_webhook_url_set",
            "mattermost_webhook_url_set",
            # branding_config is returned (so the settings form can seed the
            # current display-name override) but only written via the validated
            # public_display_name field, never as an unchecked whole-blob PATCH.
            "branding_config",
            "enabled_modules",
            "created_at",
            "updated_at",
        ]

    def get_enabled_modules(self, obj) -> list[str]:
        # What the deployment serves, not what the row stores. Already read-only
        # here (a staff PATCH carrying enabled_modules is a 403), so narrowing the
        # read cannot narrow a write. `/control/` and `module_install` keep reading
        # the raw field, because a superadmin must see and edit what is stored.
        return available_modules(obj)

    def get_telegram_bot_token_set(self, obj) -> bool:
        return bool(obj.telegram_bot_token)

    def get_smtp_password_set(self, obj) -> bool:
        return bool(obj.smtp_password)

    def get_slack_webhook_url_set(self, obj) -> bool:
        return bool(obj.slack_webhook_url)

    def get_mattermost_webhook_url_set(self, obj) -> bool:
        return bool(obj.mattermost_webhook_url)

    def validate_slack_webhook_url(self, value):
        return validate_webhook_url(value)

    def validate_mattermost_webhook_url(self, value):
        return validate_webhook_url(value)

    @extend_schema_field({"type": "string", "format": "uri", "nullable": True})
    def get_logo_url(self, obj):
        return public_image_storage.public_url(obj.logo_key) or None

    @extend_schema_field({"type": "string", "format": "uri", "nullable": True})
    def get_cover_image_url(self, obj):
        return public_image_storage.public_url(obj.cover_image_key) or None

    @extend_schema_field(
        {
            "type": "object",
            "nullable": True,
            "properties": {
                "host": {"type": "string"},
                "type": {"type": "string"},
                "value": {"type": "string"},
            },
        }
    )
    def get_domain_verification_record(self, obj):
        return domain_verification.expected_record(obj)

    @extend_schema_field({"type": "boolean"})
    def get_platform_hosting(self, obj) -> bool:
        return not domain_verification.is_self_host()

    @extend_schema_field({"type": "boolean"})
    def get_is_platform_subdomain(self, obj) -> bool:
        return (
            bool(obj.frontend_domain)
            and domain_verification._is_platform_managed(obj.frontend_domain)
            and obj.frontend_domain_status == obj.DomainStatus.VERIFIED
        )

    def validate_public_code(self, value):
        return value.upper()

    def validate_map_url(self, value):
        validate_google_maps_url(value)
        return value

    def validate_default_loan_days(self, value):
        if value < 1:
            raise serializers.ValidationError("Default loan days must be at least 1.")
        return value

    def validate_filament_low_stock_threshold_grams(self, value):
        if value < 0:
            raise serializers.ValidationError("Filament low-stock threshold cannot be negative.")
        return value

    def validate_presence_preset_minutes(self, value):
        try:
            return validate_presence_presets(value)
        except Exception as exc:
            raise serializers.ValidationError(exc.messages) from exc

    def to_internal_value(self, data):
        request = self.context.get("request")
        if request is not None and "enabled_modules" in data:
            raise PermissionDenied("Capabilities can only be changed in /control/.")
        return super().to_internal_value(data)

    def validate(self, attrs):
        effective_geofence_enabled = attrs.get("geofence_enabled", self.instance.geofence_enabled if self.instance else False)
        effective_latitude = attrs.get("geofence_latitude", self.instance.geofence_latitude if self.instance else None)
        effective_longitude = attrs.get("geofence_longitude", self.instance.geofence_longitude if self.instance else None)
        if effective_geofence_enabled and (effective_latitude is None or effective_longitude is None):
            raise serializers.ValidationError({"geofence_enabled": "Set both latitude and longitude before enabling the geofence."})

        try:
            _, enabled_features = validate_capabilities(
                attrs.get("enabled_modules", self.instance.enabled_modules if self.instance else []),
                attrs.get("enabled_features", self.instance.enabled_features if self.instance else []),
            )
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.message_dict) from exc
        if "enabled_features" in attrs:
            attrs["enabled_features"] = enabled_features
        if "resource_limit_overrides" in attrs:
            actor = self.context["request"].user
            is_superadmin = actor.is_superuser or actor.role == User.Role.SUPERADMIN
            if not is_superadmin:
                raise serializers.ValidationError(
                    {
                        "resource_limit_overrides": (
                            "Only a superadmin can set per-space resource limits."
                        )
                    }
                )
            attrs["resource_limit_overrides"] = (
                limits.validate_resource_limit_overrides(
                    attrs["resource_limit_overrides"]
                )
            )

        if "frontend_domain" in attrs:
            raw_domain = attrs.get("frontend_domain")
            normalized_domain = normalize_frontend_domain(raw_domain)
            attrs["frontend_domain"] = normalized_domain
            if normalized_domain is None and (raw_domain or "").strip():
                raise serializers.ValidationError(
                    {"frontend_domain": "Enter a valid domain, e.g. alphamakerspace.com."}
                )
            if domain_verification.domain_change_cooldown_active(self.instance, normalized_domain):
                error = {"frontend_domain": domain_verification.DOMAIN_CHANGE_COOLDOWN_MESSAGE}
                raise serializers.ValidationError(error)
            if normalized_domain is None:
                attrs["hidden_from_central_directory"] = False
                return attrs
            if not _HOSTNAME_RE.match(normalized_domain):
                raise serializers.ValidationError(
                    {"frontend_domain": "Enter a valid domain, e.g. alphamakerspace.com."}
                )

            platform_suffix = str(settings.PLATFORM_DOMAIN_SUFFIX or "").strip().lower()
            canonical = canonical_host(normalized_domain)
            current_domain = self.instance.frontend_domain if self.instance is not None else None
            domain_is_changing = normalized_domain != current_domain

            # Self-host auto-trust is superadmin-only. The staff-origin/CSRF allowlist is
            # process-global (NOT tenant-scoped), so on a multi-makerspace self-host box a
            # Space Manager who could set an arbitrary frontend_domain would inject an origin
            # into the global credentialed staff-auth allowlist — a cross-tenant token-theft
            # vector — without proving domain control. No self-governed carve-out: delegating
            # one makerspace does not license adding a process-global trusted origin. Clearing
            # a domain returns earlier (de-escalation), so only setting/changing is gated.
            if domain_is_changing and domain_verification.is_self_host():
                actor = self.context["request"].user
                is_superadmin = actor.is_superuser or actor.role == User.Role.SUPERADMIN
                if not is_superadmin:
                    raise serializers.ValidationError(
                        {
                            "frontend_domain": (
                                "Only a superadmin can set the custom domain on a "
                                "self-hosted instance."
                            )
                        }
                    )
            # Reject a tenant claiming a platform host — BOTH the apex (space-works.tech) and any
            # subdomain (*.space-works.tech). Only when the value is actually changing, so a no-op
            # PATCH that resends an already-provisioned platform domain (e.g. toggling
            # hidden_from_central_directory) still succeeds.
            platform_apex = platform_suffix.lstrip(".")
            if (
                platform_suffix
                and canonical
                and domain_is_changing
                and (canonical == platform_apex or canonical.endswith(platform_suffix))
            ):
                raise serializers.ValidationError(
                    {
                        "frontend_domain": (
                            "Platform subdomains are provisioned by staff, not set directly."
                        )
                    }
                )

            # Managed free tier: a custom (non-platform) domain requires a superadmin, or a
            # superadmin-granted per-space override (resource_limit_overrides["custom_domain"]).
            # Self-host is unaffected (is_self_host() short-circuits the whole managed program).
            if platform_suffix and domain_is_changing and not domain_verification.is_self_host():
                actor = self.context["request"].user
                is_superadmin = actor.is_superuser or actor.role == User.Role.SUPERADMIN
                override_ok = self.instance is not None and limits.custom_domain_allowed(self.instance)
                if not (is_superadmin or override_ok):
                    raise serializers.ValidationError(
                        {
                            "frontend_domain": (
                                "Custom domains aren't available on free managed hosting; "
                                "self-host to use your own domain."
                            )
                        }
                    )

            queryset = Makerspace.objects.filter(frontend_domain__iexact=normalized_domain)
            if self.instance is not None:
                queryset = queryset.exclude(pk=self.instance.pk)
            if queryset.exists():
                raise serializers.ValidationError(
                    {
                        "frontend_domain": (
                            "A makerspace with this frontend domain already exists."
                        )
                    }
                )

        effective_domain = attrs.get(
            "frontend_domain",
            self.instance.frontend_domain if self.instance is not None else None,
        )
        effective_hidden = attrs.get(
            "hidden_from_central_directory",
            self.instance.hidden_from_central_directory if self.instance is not None else False,
        )
        if effective_hidden and not effective_domain:
            raise serializers.ValidationError(
                {
                    "hidden_from_central_directory": (
                        "A frontend domain is required to hide a makerspace from the central directory."
                    )
                }
            )
        validate_smtp_settings(attrs, self.instance)
        return attrs

    def create(self, validated_data):
        public_display_name = validated_data.pop("public_display_name", None)
        if public_display_name is not None:
            branding = default_branding_config()
            branding["display_name"] = public_display_name
            validated_data["branding_config"] = branding
        instance = super().create(validated_data)
        # Self-host: a set custom domain is trusted immediately (same auto-trust as
        # update()); the superadmin-only gate is enforced in validate().
        if domain_verification.is_self_host() and instance.frontend_domain:
            instance.frontend_domain_status = Makerspace.DomainStatus.VERIFIED
            instance.domain_verified_at = timezone.now()
            instance.save(update_fields=["frontend_domain_status", "domain_verified_at", "updated_at"])
        return instance

    def update(self, instance, validated_data):
        missing = object()
        telegram_bot_token = validated_data.pop("telegram_bot_token", missing)
        smtp_password = validated_data.pop("smtp_password", missing)
        slack_webhook_url = validated_data.pop("slack_webhook_url", missing)
        mattermost_webhook_url = validated_data.pop("mattermost_webhook_url", missing)
        public_display_name = validated_data.pop("public_display_name", missing)
        new_flag = validated_data.pop("superadmin_access_enabled", None)
        with transaction.atomic():
            locked = Makerspace.objects.select_for_update().get(pk=instance.pk)
            old_domain = locked.frontend_domain
            actor = self.context["request"].user
            is_superadmin = actor.is_superuser or actor.role == User.Role.SUPERADMIN
            if new_flag is not None and new_flag != locked.superadmin_access_enabled:
                if new_flag is True and is_superadmin:
                    raise serializers.ValidationError(
                        {
                            "superadmin_access_enabled": (
                                "Only the makerspace admin can re-enable superadmin access."
                            )
                        }
                    )
                if new_flag is False and not platform_email_configured():
                    raise serializers.ValidationError(
                        {
                            "superadmin_access_enabled": (
                                "Configure Platform Email before disabling superadmin access, "
                                "so password recovery remains possible."
                            )
                        }
                    )
                locked.superadmin_access_enabled = new_flag
            for field, value in validated_data.items():
                setattr(locked, field, value)
            if "frontend_domain" in validated_data and validated_data["frontend_domain"] != old_domain:
                # Re-check the self-host superadmin gate UNDER THE ROW LOCK. validate() compared
                # the incoming value against a possibly-stale instance, so a concurrent superadmin
                # change between validate() and this lock could turn a non-superadmin's apparent
                # no-op PATCH into a real (auto-verified) change to the trusted origin.
                if (
                    domain_verification.is_self_host()
                    and validated_data["frontend_domain"]
                    and not is_superadmin
                ):
                    raise serializers.ValidationError(
                        {
                            "frontend_domain": (
                                "Only a superadmin can set the custom domain on a "
                                "self-hosted instance."
                            )
                        }
                    )
                locked.frontend_domain_changed_at = timezone.now()
                if domain_verification.is_self_host() and validated_data["frontend_domain"]:
                    locked.frontend_domain_status = Makerspace.DomainStatus.VERIFIED
                    locked.domain_verified_at = timezone.now()
                else:
                    locked.frontend_domain_status = Makerspace.DomainStatus.PENDING
                    locked.domain_verified_at = None
            if public_display_name is not missing:
                # Merge into the FRESH locked row's branding_config so we never
                # overwrite support_email/support_url from a stale client copy.
                branding = dict(locked.branding_config or {})
                branding["display_name"] = public_display_name
                locked.branding_config = branding
            if telegram_bot_token is not missing:
                locked.set_telegram_bot_token(telegram_bot_token)
            if smtp_password is not missing:
                locked.set_smtp_password(smtp_password)
            if slack_webhook_url is not missing:
                locked.set_slack_webhook_url(slack_webhook_url)
            if mattermost_webhook_url is not missing:
                locked.set_mattermost_webhook_url(mattermost_webhook_url)
            locked.save()
            return locked
