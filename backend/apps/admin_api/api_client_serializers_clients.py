from urllib.parse import urlsplit

from rest_framework import serializers

from apps.accounts import rbac
from apps.accounts.models import User
from apps.apiclients.models import ApiClient, ApiKeyRequest
from apps.apiclients.scope_registry import BROWSER_SCOPES, SCOPE_VOCABULARY


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
            "id", "label", "client_id", "client_type", "scopes",
            "rate_limit_tier", "makerspace", "public_makerspace_code",
            "allowed_origins", "backend_base_url", "public_api_base_url",
            "is_active", "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "client_id", "makerspace", "public_makerspace_code",
            "backend_base_url", "public_api_base_url", "created_at", "updated_at",
        ]

    def validate_allowed_origins(self, value):
        if not value:
            raise serializers.ValidationError("At least one frontend origin is required.")
        for origin in value:
            if not isinstance(origin, str) or not origin.startswith(("http://", "https://")):
                raise serializers.ValidationError("Origins must be exact http(s) URLs.")
        return value

    def validate_scopes(self, value):
        # DRF runs field validation BEFORE the object-level validate() that strips the
        # privileged fields a non-superadmin may not set. Validating unconditionally would
        # turn a stale value from a tenant manager into a 400 where the endpoint contract
        # has always been to ignore the field -- so only the actor who can actually set
        # scopes is held to the vocabulary.
        if not self._actor_may_set_privileged_fields():
            return value
        unknown = sorted(set(value) - SCOPE_VOCABULARY)
        if unknown:
            raise serializers.ValidationError(
                f"Unknown API-client scope(s): {', '.join(unknown)}."
            )
        return value

    def _actor_may_set_privileged_fields(self):
        """Whether this actor may set client_type / scopes / rate_limit_tier.

        Shared by field-level and object-level validation so the two layers cannot
        disagree about who is privileged.
        """
        request = self.context.get("request")
        actor = getattr(request, "user", None)
        is_superadmin = bool(
            actor and (
                actor.is_superuser
                or getattr(actor, "role", None) == User.Role.SUPERADMIN
            )
        )
        if not is_superadmin:
            return False
        makerspace_id = (
            getattr(self.instance, "makerspace_id", None)
            or self.context.get("makerspace_id")
        )
        if makerspace_id is None:
            return True
        return int(makerspace_id) not in rbac.superadmin_hidden_makerspace_ids()

    def validate(self, attrs):
        # Non-superadmins cannot set client trust knobs. Until a tenant scope picker
        # exists, ApiClient.issue supplies the frozen legacy capability after these
        # fields are removed.
        has_global_privilege = self._actor_may_set_privileged_fields()
        if not has_global_privilege:
            for field in ("client_type", "scopes", "rate_limit_tier"):
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


class ApiClientCreateResponseSerializer(ApiClientSerializer):
    client_secret = serializers.CharField(read_only=True)

    class Meta(ApiClientSerializer.Meta):
        fields = [
            "id", "label", "client_id", "client_secret", "client_type", "scopes",
            "rate_limit_tier", "makerspace", "public_makerspace_code",
            "allowed_origins", "backend_base_url", "public_api_base_url",
            "is_active", "created_at", "updated_at",
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
