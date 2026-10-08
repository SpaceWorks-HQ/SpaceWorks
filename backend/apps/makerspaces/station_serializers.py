"""Bounded request/response schemas for kiosk Station admin, session and lease."""

from rest_framework import serializers

from apps.makerspaces.models_stations import Station


KIOSK_KIND_CHOICES = (
    (Station.Kind.SCANNER, "Scanner"),
    (Station.Kind.HANDOVER, "Handover"),
)


class KioskStationCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=160, trim_whitespace=True)
    kind = serializers.ChoiceField(choices=KIOSK_KIND_CHOICES)


class KioskStationSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    kind = serializers.CharField()
    enabled = serializers.BooleanField()
    public_token = serializers.UUIDField(allow_null=True)
    version = serializers.IntegerField(allow_null=True)
    station_url = serializers.CharField(allow_null=True)
    rotated_at = serializers.DateTimeField(allow_null=True)
    created_at = serializers.DateTimeField()


class KioskStationSecretSerializer(KioskStationSerializer):
    pin = serializers.CharField()


class KioskStationRevealSerializer(serializers.Serializer):
    current_password = serializers.CharField(trim_whitespace=False, write_only=True)


class KioskStationRevealResponseSerializer(serializers.Serializer):
    pin = serializers.CharField()
    version = serializers.IntegerField()


class KioskStationPinSerializer(serializers.Serializer):
    pin = serializers.RegexField(r"^\d{8}$", write_only=True)
    # Central mode only: the route slug the page was loaded under. The server still
    # resolves the tenant from the Station token and refuses a mismatch.
    makerspace_slug = serializers.SlugField(required=False, max_length=80)


class _StationRefSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    kind = serializers.CharField()


class _MakerspaceRefSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    slug = serializers.CharField()
    name = serializers.CharField()


class KioskStationBootstrapSerializer(serializers.Serializer):
    station = _StationRefSerializer()
    makerspace = _MakerspaceRefSerializer()
    session_expires_at = serializers.DateTimeField()
    permitted_operations = serializers.ListField(child=serializers.CharField())


class KioskOperatorLeaseSerializer(serializers.Serializer):
    lease_token = serializers.CharField()
    lease_id = serializers.UUIDField()
    expires_at = serializers.DateTimeField()
    allowed_actions = serializers.ListField(child=serializers.CharField())
    permitted_operations = serializers.ListField(child=serializers.CharField())
