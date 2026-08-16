"""OpenAPI serializers for browser session endpoints."""

from drf_spectacular.utils import inline_serializer
from rest_framework import serializers


AuthMembershipSerializer = inline_serializer(
    name="AuthMembership",
    fields={
        "id": serializers.IntegerField(),
        "slug": serializers.CharField(),
        "role": serializers.CharField(),
        "role_id": serializers.IntegerField(allow_null=True),
        "role_name": serializers.CharField(),
        "role_slug": serializers.CharField(),
        "actions": serializers.ListField(child=serializers.CharField()),
        "can_configure_machine_types": serializers.BooleanField(),
        "is_machine_only": serializers.BooleanField(),
        "can_refer": serializers.BooleanField(),
        "can_verify": serializers.BooleanField(),
        "verified_at": serializers.DateTimeField(allow_null=True),
        "referrals_enabled": serializers.BooleanField(),
    },
)
UserPayloadSerializer = inline_serializer(
    name="AuthUserPayload",
    fields={
        "id": serializers.IntegerField(),
        "username": serializers.CharField(),
        "email": serializers.EmailField(),
        "display_name": serializers.CharField(),
        "phone": serializers.CharField(),
        "email_verified": serializers.BooleanField(),
        "role": serializers.CharField(),
        "is_superuser": serializers.BooleanField(),
        "must_change_password": serializers.BooleanField(),
        "makerspaces": serializers.ListField(child=AuthMembershipSerializer),
    },
)
LoginRequestSerializer = inline_serializer(
    name="LoginRequest",
    fields={
        "username": serializers.CharField(),
        "password": serializers.CharField(write_only=True),
    },
)
LoginResponseSerializer = inline_serializer(
    name="LoginResponse",
    fields={
        "access": serializers.CharField(),
        "user": UserPayloadSerializer,
    },
)
RefreshResponseSerializer = inline_serializer(
    name="RefreshResponse", fields={"access": serializers.CharField()}
)
LogoutResponseSerializer = inline_serializer(
    name="LogoutResponse", fields={"detail": serializers.CharField()}
)
