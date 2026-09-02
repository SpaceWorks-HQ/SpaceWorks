from rest_framework import serializers


class StationPinSerializer(serializers.Serializer):
    pin = serializers.RegexField(r"^\d{8}$", write_only=True)


class StationRevealSerializer(serializers.Serializer):
    current_password = serializers.CharField(trim_whitespace=False, write_only=True)


class StationStatusSerializer(serializers.Serializer):
    configured = serializers.BooleanField()
    enabled = serializers.BooleanField(required=False)
    public_token = serializers.UUIDField(required=False)
    version = serializers.IntegerField(required=False)
    station_url = serializers.URLField(required=False)
    rotated_at = serializers.DateTimeField(required=False)


class StationRotationSerializer(serializers.Serializer):
    pin = serializers.CharField()
    public_token = serializers.UUIDField()
    version = serializers.IntegerField()
    station_url = serializers.URLField()


class StationRevealResponseSerializer(serializers.Serializer):
    pin = serializers.CharField()
    version = serializers.IntegerField()
