from rest_framework import serializers

from apps.accounts.views import UserPayloadSerializer


class ClaimRedemptionSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=64, trim_whitespace=True, write_only=True)
    makerspace_slug = serializers.SlugField(max_length=80, write_only=True)


class ClaimRedemptionResponseSerializer(serializers.Serializer):
    access = serializers.CharField()
    # `inline_serializer` returns an INSTANCE, not a class -- every other call site
    # (views.py:88, :360) passes it through unchanged, and calling it raises at import
    # time, which takes the whole URL conf down rather than failing locally.
    user = UserPayloadSerializer
