from urllib.parse import urlsplit

from rest_framework import serializers

from apps.apiclients.models import ApiClient, ApiKeyRequest
from apps.apiclients.scope_grants import (
    actor_may_grant_privileged_scopes,
    validate_grantable_scopes,
)
from apps.apiclients.scope_registry import BROWSER_SCOPES


class ApiClientSerializer(serializers.ModelSerializer):
    scopes = serializers.ListField(
        child=serializers.CharField(), required=True, allow_empty=False
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
            "id", "label", "client_id", "client_type", "scopes",
            "rate_limit_tier", "makerspace", "public_makerspace_code",
            "allowed_origins", "backend_base_url", "public_api_base_url",
            "is_active", "last_seen_at", "last_seen_ip", "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "client_id", "makerspace", "public_makerspace_code",
            "backend_base_url", "public_api_base_url", "created_at", "updated_at",
            "last_seen_at", "last_seen_ip",
        ]

    def validate_allowed_origins(self, value):
        if not value:
            raise serializers.ValidationError("At least one frontend origin is required.")
        for origin in value:
            if not isinstance(origin, str) or not origin.startswith(("http://", "https://")):
                raise serializers.ValidationError("Origins must be exact http(s) URLs.")
        return value

    def validate_scopes(self, value):
        try:
            return validate_grantable_scopes(
                value,
                privileged=self._actor_may_set_privileged_fields(),
            )
        except ValueError as exc:
            raise serializers.ValidationError(str(exc)) from exc

    def _actor_may_set_privileged_fields(self):
        """Whether this actor may set globally privileged client fields/scopes.

        Shared by field-level and object-level validation so the two layers cannot
        disagree about who is privileged.
        """
        request = self.context.get("request")
        actor = getattr(request, "user", None)
        makerspace_id = (
            getattr(self.instance, "makerspace_id", None)
            or self.context.get("makerspace_id")
        )
        return actor_may_grant_privileged_scopes(actor, makerspace_id)

    def validate(self, attrs):
        # Trust knobs remain global-only. Scope validation instead applies the tenant
        # grant ceiling, so tenant input is explicit and never silently discarded.
        has_global_privilege = self._actor_may_set_privileged_fields()
        if not has_global_privilege:
            for field in ("client_type", "rate_limit_tier"):
                attrs.pop(field, None)
        client_type = attrs.get("client_type") or getattr(
            self.instance, "client_type", "server"
        )
        scopes = attrs.get("scopes", getattr(self.instance, "scopes", []))
        if client_type == "browser" and not set(scopes or []).issubset(BROWSER_SCOPES):
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


class ApiClientScopeOptionSerializer(serializers.Serializer):
    value = serializers.CharField()
    label = serializers.CharField()
    description = serializers.CharField()
    group = serializers.CharField()
    grantable = serializers.BooleanField()
    lock_reason = serializers.CharField(allow_null=True)


class ApiClientCreateResponseSerializer(ApiClientSerializer):
    client_secret = serializers.CharField(read_only=True)

    class Meta(ApiClientSerializer.Meta):
        fields = [
            "id", "label", "client_id", "client_secret", "client_type", "scopes",
            "rate_limit_tier", "makerspace", "public_makerspace_code",
            "allowed_origins", "backend_base_url", "public_api_base_url",
            "is_active", "last_seen_at", "last_seen_ip", "created_at", "updated_at",
        ]
        read_only_fields = [
            *ApiClientSerializer.Meta.read_only_fields,
            "client_secret",
        ]


class ApiKeyRequestSerializer(serializers.ModelSerializer):
    # Required explicitly so the model's blank/default=list cannot bypass validation.
    allowed_origins = serializers.ListField(
        child=serializers.CharField(), allow_empty=False
    )

    class Meta:
        model = ApiKeyRequest
        fields = [
            "id", "makerspace", "label", "reason", "allowed_origins", "status",
            "resolution_note", "created_at", "resolved_at",
        ]
        read_only_fields = [
            "id", "status", "resolution_note", "created_at", "resolved_at",
        ]

    def validate_allowed_origins(self, value):
        # Store the same bare origin shape browsers send in their Origin header.
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
