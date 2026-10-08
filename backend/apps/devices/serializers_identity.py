"""Device API contracts: one read shape, a narrow create, and a two-field PATCH.

Tenancy, status, key material, version, last-seen/offline markers and provenance are
read-only everywhere. ``kind`` is set once at creation. Unknown fields are rejected
rather than ignored, so a client cannot believe it changed something it did not.
"""

from rest_framework import serializers

from apps.devices.models import Device, DeviceEnrollment

MAX_OFFLINE_THRESHOLD_SECONDS = 7 * 24 * 3600


class StrictSerializer(serializers.Serializer):
    def validate(self, attrs):
        unknown = set(getattr(self, "initial_data", {}) or {}) - set(self.fields)
        if unknown:
            raise serializers.ValidationError(
                {field: "This field cannot be set." for field in sorted(unknown)}
            )
        return attrs


def _name_field(**kwargs):
    return serializers.CharField(max_length=120, trim_whitespace=True, allow_blank=False, **kwargs)


def _threshold_field(**kwargs):
    return serializers.IntegerField(min_value=1, max_value=MAX_OFFLINE_THRESHOLD_SECONDS, **kwargs)


class DeviceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Device
        fields = (
            "id", "makerspace", "kind", "name", "status", "public_key", "key_fingerprint",
            "key_version", "last_seen_at", "offline_threshold_seconds", "offline_since",
            "offline_notified_at", "created_by", "created_at", "revoked_at", "revoked_by",
        )
        read_only_fields = fields


class DeviceCreateSerializer(StrictSerializer):
    kind = serializers.ChoiceField(choices=Device.Kind.choices)
    name = _name_field()
    offline_threshold_seconds = _threshold_field(required=False, default=300)


class DeviceUpdateSerializer(StrictSerializer):
    name = _name_field(required=False)
    offline_threshold_seconds = _threshold_field(required=False)

    def validate(self, attrs):
        attrs = super().validate(attrs)
        if not attrs:
            raise serializers.ValidationError("Provide name or offline_threshold_seconds.")
        return attrs


class EnrollmentGrantSerializer(serializers.Serializer):
    """Returned exactly once: the raw token is never stored and cannot be re-read."""

    enrollment_id = serializers.UUIDField()
    device_id = serializers.UUIDField()
    purpose = serializers.ChoiceField(choices=DeviceEnrollment.Purpose.choices)
    token = serializers.CharField()
    expires_at = serializers.DateTimeField()

    @staticmethod
    def payload(enrollment, token):
        return {
            "enrollment_id": enrollment.pk, "device_id": enrollment.device_id,
            "purpose": enrollment.purpose, "token": token, "expires_at": enrollment.expires_at,
        }


class DeviceCreatedSerializer(serializers.Serializer):
    device = DeviceSerializer()
    enrollment = EnrollmentGrantSerializer()


class ChallengeRequestSerializer(StrictSerializer):
    token = serializers.CharField(max_length=256)
    public_key = serializers.CharField(max_length=64)


class ChallengeResponseSerializer(serializers.Serializer):
    challenge = serializers.CharField()
    expires_at = serializers.DateTimeField()


class CompleteRequestSerializer(ChallengeRequestSerializer):
    challenge = serializers.CharField(max_length=64)
    signature = serializers.CharField(max_length=128)


class DeviceIdentitySerializer(serializers.Serializer):
    device_id = serializers.UUIDField(source="pk")
    makerspace_id = serializers.IntegerField()
    status = serializers.CharField()
    key_version = serializers.IntegerField()
    last_seen_at = serializers.DateTimeField(allow_null=True)
