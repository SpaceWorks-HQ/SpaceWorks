from rest_framework import serializers
from apps.accounts.schemas_auth import UserPayloadSerializer


class MFAChallengeResponseSerializer(serializers.Serializer):
    mfa_required = serializers.BooleanField()
    enrollment_required = serializers.BooleanField()
    challenge = serializers.CharField()
    expires_in = serializers.IntegerField()


class MFAChallengeSerializer(serializers.Serializer):
    challenge = serializers.CharField(min_length=20, max_length=200, write_only=True)


class MFAVerifySerializer(MFAChallengeSerializer):
    code = serializers.CharField(min_length=6, max_length=64, write_only=True, trim_whitespace=True)


class MFAEnrollmentSerializer(serializers.Serializer):
    secret = serializers.CharField()
    provisioning_uri = serializers.CharField()
    qr_data_url = serializers.CharField()


class MFACompletedSerializer(serializers.Serializer):
    access = serializers.CharField()
    surface = serializers.CharField()
    user = UserPayloadSerializer
    refresh = serializers.CharField(required=False)
    device_grant = serializers.DictField(required=False)
    recovery_codes = serializers.ListField(child=serializers.CharField(), required=False)


class MFAPasswordSerializer(serializers.Serializer):
    password = serializers.CharField(max_length=1024, write_only=True, trim_whitespace=False)


class MFAStatusSerializer(serializers.Serializer):
    enabled = serializers.BooleanField()
    required = serializers.BooleanField()


class MFARecoverySerializer(serializers.Serializer):
    recovery_codes = serializers.ListField(child=serializers.CharField())
