from urllib.parse import urlsplit

from rest_framework import serializers

from apps.accounts import rbac
from apps.accounts.models import User
from apps.apiclients.models import ApiClient, ApiKeyRequest
from apps.integrations.smtp_validation import validate_smtp_settings
from apps.integrations.webhook_validation import validate_webhook_url
from apps.makerspaces.models import Makerspace


class ApiClientSerializer(serializers.ModelSerializer):
    scopes = serializers.ListField(
        child=serializers.CharField(), required=False, allow_empty=True
    )
    allowed_origins = serializers.ListField(
        child=serializers.CharField(), allow_empty=False
    )
    backend_base_url = serializers.SerializerMethodField()
    public_api_base_url = serializers.SerializerMethodField()
    public_makerspace_code = serializers.CharField(
        source="makerspace.public_code",
        read_only=True,
    )

    class Meta:
        model = ApiClient
        fields = [
            "id",
            "label",
            "client_id",
            "client_type",
            "scopes",
            "rate_limit_tier",
            "makerspace",
            "public_makerspace_code",
            "allowed_origins",
            "backend_base_url",
            "public_api_base_url",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "client_id",
            "makerspace",
            "public_makerspace_code",
            "backend_base_url",
            "public_api_base_url",
            "created_at",
            "updated_at",
        ]

    def validate_allowed_origins(self, value):
        if not value:
            raise serializers.ValidationError("At least one frontend origin is required.")
        for origin in value:
            if not isinstance(origin, str) or not origin.startswith(("http://", "https://")):
                raise serializers.ValidationError("Origins must be exact http(s) URLs.")
        return value

    def validate(self, attrs):
        # Privilege gate: this endpoint is now reachable by makerspace admins (MANAGE_MAKERSPACE),
        # not just superadmins. Non-superadmins may NOT set the privileged knobs (rate-limit tier,
        # scopes, client_type) â€” otherwise a Space Manager could self-issue a `trusted`-tier client
        # with `admin:write` scopes. Drop them: on create the view's safe defaults
        # (server / [] / standard) apply; on update the existing superadmin-set values are preserved.
        request = self.context.get("request")
        actor = getattr(request, "user", None)
        is_superadmin = bool(
            actor and (actor.is_superuser or getattr(actor, "role", None) == User.Role.SUPERADMIN)
        )
        makerspace_id = getattr(self.instance, "makerspace_id", None) or self.context.get("makerspace_id")
        hidden_ids = rbac.superadmin_hidden_makerspace_ids() if is_superadmin and makerspace_id else set()
        has_global_privilege = is_superadmin and (
            makerspace_id is None or int(makerspace_id) not in hidden_ids
        )
        if not has_global_privilege:
            for field in ("client_type", "scopes", "rate_limit_tier"):
                attrs.pop(field, None)
        client_type = attrs.get("client_type") or getattr(self.instance, "client_type", "server")
        scopes = attrs.get("scopes", getattr(self.instance, "scopes", []))
        if client_type == "browser":
            forbidden = {"inventory:write", "requests:review", "admin:write", "qr:manage"}
            if forbidden.intersection(set(scopes or [])):
                raise serializers.ValidationError(
                    {"scopes": "Browser clients may only use public/read scopes."}
                )
        return attrs

    def get_backend_base_url(self, _obj) -> str:
        request = self.context.get("request")
        return request.build_absolute_uri("/").rstrip("/") if request else ""

    def get_public_api_base_url(self, obj) -> str:
        request = self.context.get("request")
        if not request:
            return ""
        code = obj.makerspace.public_code if obj.makerspace_id else ""
        return request.build_absolute_uri(f"/api/v1/public/{code}/").rstrip("/")

class ApiClientCreateResponseSerializer(ApiClientSerializer):
    client_secret = serializers.CharField(read_only=True)

    class Meta(ApiClientSerializer.Meta):
        fields = [
            "id",
            "label",
            "client_id",
            "client_secret",
            "client_type",
            "scopes",
            "rate_limit_tier",
            "makerspace",
            "public_makerspace_code",
            "allowed_origins",
            "backend_base_url",
            "public_api_base_url",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            *ApiClientSerializer.Meta.read_only_fields,
            "client_secret",
        ]


class ApiKeyRequestSerializer(serializers.ModelSerializer):
    # Declared explicitly + required so validate_allowed_origins always runs (the model field
    # is blank/default=list, which would otherwise let DRF skip it when omitted and approve an
    # origin-less request into an unusable client).
    allowed_origins = serializers.ListField(
        child=serializers.CharField(), allow_empty=False
    )

    class Meta:
        model = ApiKeyRequest
        fields = [
            "id",
            "makerspace",
            "label",
            "reason",
            "allowed_origins",
            "status",
            "resolution_note",
            "created_at",
            "resolved_at",
        ]
        read_only_fields = [
            "id",
            "status",
            "resolution_note",
            "created_at",
            "resolved_at",
        ]

    def validate_allowed_origins(self, value):
        # Must be a non-empty list of EXACT scheme://host[:port] origins. CORS and the
        # API-client middleware compare against the browser Origin (no path/trailing slash),
        # so anything with a path/query/fragment would be stored but never match after
        # approval. Reject those and normalize to scheme://netloc so the issued key works.
        if not value:
            raise serializers.ValidationError("At least one frontend origin is required.")
        if not isinstance(value, list):
            raise serializers.ValidationError("Origins must be a list of http(s) URLs.")
        normalized = []
        for origin in value:
            if not isinstance(origin, str):
                raise serializers.ValidationError("Origins must be exact http(s) URLs.")
            parts = urlsplit(origin.strip())
            if parts.scheme not in ("http", "https") or not parts.netloc:
                raise serializers.ValidationError("Origins must be exact http(s) URLs.")
            if parts.path not in ("", "/") or parts.query or parts.fragment:
                raise serializers.ValidationError(
                    "Origins must be a bare scheme://host[:port] with no path."
                )
            normalized.append(f"{parts.scheme}://{parts.netloc}")
        return normalized


class ApiIntegrationSettingsSerializer(serializers.ModelSerializer):
    public_api_key = serializers.CharField(read_only=True)
    cors_allowed_origins = serializers.ListField(
        child=serializers.CharField(),
        read_only=True,
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

    class Meta:
        model = Makerspace
        fields = [
            "public_code",
            "public_api_key",
            "cors_allowed_origins",
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
        ]
        read_only_fields = [
            "public_code",
            "public_api_key",
            "cors_allowed_origins",
            "telegram_bot_token_set",
            "smtp_password_set",
            "slack_webhook_url_set",
            "mattermost_webhook_url_set",
            "discord_webhook_url_set",
        ]

    def get_telegram_bot_token_set(self, obj) -> bool:
        return bool(obj.telegram_bot_token)

    def get_smtp_password_set(self, obj) -> bool:
        return bool(obj.smtp_password)

    def get_slack_webhook_url_set(self, obj) -> bool:
        return bool(obj.slack_webhook_url)

    def get_mattermost_webhook_url_set(self, obj) -> bool:
        return bool(obj.mattermost_webhook_url)

    def get_discord_webhook_url_set(self, obj) -> bool:
        return bool(obj.discord_webhook_url)

    def validate_slack_webhook_url(self, value):
        return validate_webhook_url(value)

    def validate_mattermost_webhook_url(self, value):
        return validate_webhook_url(value)

    def validate_discord_webhook_url(self, value):
        return validate_webhook_url(value)

    def validate_default_loan_days(self, value):
        if value < 1:
            raise serializers.ValidationError("Default loan days must be at least 1.")
        return value

    def validate(self, attrs):
        validate_smtp_settings(attrs, self.instance)
        return attrs

    def update(self, instance, validated_data):
        missing = object()
        telegram_bot_token = validated_data.pop("telegram_bot_token", missing)
        smtp_password = validated_data.pop("smtp_password", missing)
        slack_webhook_url = validated_data.pop("slack_webhook_url", missing)
        mattermost_webhook_url = validated_data.pop("mattermost_webhook_url", missing)
        discord_webhook_url = validated_data.pop("discord_webhook_url", missing)
        for field, value in validated_data.items():
            setattr(instance, field, value)
        if telegram_bot_token is not missing:
            instance.set_telegram_bot_token(telegram_bot_token)
        if smtp_password is not missing:
            instance.set_smtp_password(smtp_password)
        if slack_webhook_url is not missing:
            instance.set_slack_webhook_url(slack_webhook_url)
        if mattermost_webhook_url is not missing:
            instance.set_mattermost_webhook_url(mattermost_webhook_url)
        if discord_webhook_url is not missing:
            instance.set_discord_webhook_url(discord_webhook_url)
        instance.save()
        return instance
