from urllib.parse import urlsplit

from rest_framework import serializers

from apps.backup.models import BackupDestination, BackupDestinationUpload


class BackupDestinationSerializer(serializers.ModelSerializer):
    """Credentials are write-only; reads report only whether they are stored."""

    access_key_id = serializers.CharField(
        write_only=True, required=False, allow_blank=False, max_length=200
    )
    secret_access_key = serializers.CharField(
        write_only=True, required=False, allow_blank=False, max_length=200,
        trim_whitespace=False,
    )
    credentials_set = serializers.SerializerMethodField()

    class Meta:
        model = BackupDestination
        fields = (
            "id", "name", "kind", "endpoint_url", "bucket", "region", "prefix",
            "addressing_style", "access_key_id", "secret_access_key", "credentials_set",
            "enabled", "retention_days", "created_at", "updated_at", "retired_at",
            "last_success_at", "last_error_code",
        )
        read_only_fields = (
            "id", "kind", "credentials_set", "created_at", "updated_at", "retired_at",
            "last_success_at", "last_error_code",
        )

    def get_credentials_set(self, obj) -> bool:
        return bool(obj.access_key_id and obj.secret_access_key)

    def validate_endpoint_url(self, value):
        if value and urlsplit(value).scheme not in {"http", "https"}:
            raise serializers.ValidationError("The endpoint must be an http(s) URL.")
        return value

    def validate_prefix(self, value):
        value = value.strip("/")
        if ".." in value.split("/"):
            raise serializers.ValidationError("The prefix may not contain '..'.")
        return value

    def validate(self, attrs):
        if self.instance is None and not (
            attrs.get("access_key_id") and attrs.get("secret_access_key")
        ):
            raise serializers.ValidationError(
                {"credentials": "Both access_key_id and secret_access_key are required."}
            )
        if self.instance is not None and self.instance.retired_at is not None:
            raise serializers.ValidationError("A retired destination cannot be changed.")
        if self.instance is not None and self.instance.uploads.exists():
            # Journal locators address this bucket/endpoint. Moving it would strand
            # every recorded copy and send retention deletes to the wrong store.
            for field in ("endpoint_url", "bucket", "region", "prefix", "addressing_style"):
                if field in attrs and attrs[field] != getattr(self.instance, field):
                    raise serializers.ValidationError({
                        field: "This destination already has a journal; register a new destination to change its location.",
                    })
        return attrs

    def create(self, validated_data):
        access = validated_data.pop("access_key_id")
        secret = validated_data.pop("secret_access_key")
        destination = BackupDestination(**validated_data)
        destination.set_access_key_id(access)
        destination.set_secret_access_key(secret)
        destination.save()
        return destination

    def update(self, instance, validated_data):
        access = validated_data.pop("access_key_id", None)
        secret = validated_data.pop("secret_access_key", None)
        if access is not None:
            instance.set_access_key_id(access)
        if secret is not None:
            instance.set_secret_access_key(secret)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        return instance


def audit_meta(validated_data):
    """Field names only for credentials -- never their values."""
    meta = {
        key: value for key, value in validated_data.items()
        if key not in {"access_key_id", "secret_access_key"}
    }
    meta["credentials_changed"] = sorted(
        key for key in ("access_key_id", "secret_access_key") if key in validated_data
    )
    return meta


class BackupDestinationUploadSerializer(serializers.ModelSerializer):
    destination = serializers.SlugRelatedField(slug_field="name", read_only=True)

    class Meta:
        model = BackupDestinationUpload
        fields = (
            "id", "destination", "archive_id_snapshot", "scope_snapshot",
            "makerspace_id_snapshot", "archive_completed_at_snapshot", "expected_size_bytes",
            "expected_sha256", "integrity_source", "remote_locator", "state", "attempts",
            "next_attempt_at", "uploaded_at", "verified_at", "expires_at", "deleted_at",
            "last_error_code",
        )
        read_only_fields = fields


class RehydrateSerializer(serializers.Serializer):
    destination = serializers.PrimaryKeyRelatedField(
        queryset=BackupDestination.objects.filter(retired_at__isnull=True)
    )


class DestinationProbeSerializer(serializers.Serializer):
    ok = serializers.BooleanField()
    error_code = serializers.CharField(allow_blank=True)


class DestinationDispatchSerializer(serializers.Serializer):
    detail = serializers.CharField()


class BackupDestinationPageSerializer(serializers.Serializer):
    count = serializers.IntegerField()
    next = serializers.URLField(allow_null=True)
    previous = serializers.URLField(allow_null=True)
    results = BackupDestinationSerializer(many=True)


class BackupDestinationUploadPageSerializer(serializers.Serializer):
    count = serializers.IntegerField()
    next = serializers.URLField(allow_null=True)
    previous = serializers.URLField(allow_null=True)
    results = BackupDestinationUploadSerializer(many=True)
