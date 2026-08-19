from rest_framework import serializers

from apps.accounts.models_social import (
    SocialClientPlatform,
    SocialDelivery,
    SocialProvider,
    SocialSurface,
)
from apps.accounts.models_oidc import provider_for_slug, slug_from_provider_key


class SocialProviderKeyField(serializers.CharField):
    def __init__(self, **kwargs):
        super().__init__(max_length=64, **kwargs)

    def to_internal_value(self, data):
        value = super().to_internal_value(data)
        if value in SocialProvider.values:
            return value
        slug = slug_from_provider_key(value)
        if slug is None or provider_for_slug(slug) is None:
            self.fail("invalid")
        return value


class SocialNonceSerializer(serializers.Serializer):
    provider = SocialProviderKeyField()
    surface = serializers.ChoiceField(choices=SocialSurface.choices)
    delivery = serializers.ChoiceField(choices=SocialDelivery.choices)
    client_platform = serializers.ChoiceField(choices=SocialClientPlatform.choices)
    challenge = serializers.CharField(
        max_length=512, required=False, write_only=True, trim_whitespace=False
    )

    def validate(self, attrs):
        if (attrs["delivery"] == "web") != (attrs["client_platform"] == "web"):
            raise serializers.ValidationError(
                "Web delivery requires the web client platform."
            )
        grant = getattr(self.context.get("request"), "device_grant", None)
        has_challenge = bool(attrs.get("challenge"))
        if attrs["delivery"] == SocialDelivery.WEB and has_challenge:
            raise serializers.ValidationError("Web social login cannot use attestation.")
        if attrs["delivery"] == SocialDelivery.DEVICE and (
            (grant is None) != has_challenge
        ):
            raise serializers.ValidationError(
                "A first device login requires an attestation challenge."
            )
        return attrs


class SocialLoginSerializer(serializers.Serializer):
    id_token = serializers.CharField(max_length=16384, write_only=True)
    nonce = serializers.CharField(max_length=512, write_only=True)
    surface = serializers.ChoiceField(choices=SocialSurface.choices)
    delivery = serializers.ChoiceField(choices=SocialDelivery.choices)
    client_platform = serializers.ChoiceField(choices=SocialClientPlatform.choices)
    apple_name = serializers.CharField(
        max_length=200, required=False, allow_blank=True, trim_whitespace=True
    )
    challenge = serializers.CharField(
        max_length=512, required=False, write_only=True, trim_whitespace=False
    )
    attestation = serializers.JSONField(required=False, write_only=True)

    def validate_attestation(self, value):
        if not isinstance(value, dict) or not value or len(value) > 16:
            raise serializers.ValidationError("Invalid attestation payload.")
        return value

    def validate(self, attrs):
        if (attrs["delivery"] == "web") != (attrs["client_platform"] == "web"):
            raise serializers.ValidationError("Invalid social delivery platform.")
        grant = getattr(self.context.get("request"), "device_grant", None)
        has_attestation = bool(attrs.get("challenge")) and bool(
            attrs.get("attestation")
        )
        if bool(attrs.get("challenge")) != bool(attrs.get("attestation")):
            raise serializers.ValidationError(
                "The challenge and attestation must be presented together."
            )
        if attrs["delivery"] == SocialDelivery.WEB and has_attestation:
            raise serializers.ValidationError("Web social login cannot use attestation.")
        if attrs["delivery"] == SocialDelivery.DEVICE and (
            (grant is None) != has_attestation
        ):
            raise serializers.ValidationError(
                "A first device login requires attestation."
            )
        return attrs


class SocialLinkSerializer(serializers.Serializer):
    provider = SocialProviderKeyField()
    id_token = serializers.CharField(max_length=16384, write_only=True)
    nonce = serializers.CharField(max_length=512, write_only=True)
    client_platform = serializers.ChoiceField(
        choices=SocialClientPlatform.choices, default=SocialClientPlatform.WEB
    )
    apple_name = serializers.CharField(
        max_length=200, required=False, allow_blank=True, trim_whitespace=True
    )

    def validate_client_platform(self, value):
        if value != SocialClientPlatform.WEB:
            raise serializers.ValidationError("Browser linking requires the web client.")
        return value


class SocialIdentitySerializer(serializers.Serializer):
    provider = serializers.CharField()
    created_at = serializers.DateTimeField()
    updated_at = serializers.DateTimeField()


class SocialNonceResponseSerializer(serializers.Serializer):
    nonce = serializers.CharField()
    expires_in = serializers.IntegerField()


class SocialLoginResponseSerializer(serializers.Serializer):
    access = serializers.CharField()
    refresh = serializers.CharField(required=False)
    device_grant = serializers.DictField(required=False)
    user = serializers.DictField()
    outcome = serializers.CharField()
