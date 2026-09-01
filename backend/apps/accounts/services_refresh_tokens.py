"""Serialized rotation for persisted SimpleJWT refresh tokens."""

from django.db import transaction
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.settings import api_settings
from rest_framework_simplejwt.token_blacklist.models import (
    BlacklistedToken,
    OutstandingToken,
)


def rotate_refresh_token(raw_refresh, *, token_class, validate, mint):
    """Consume one refresh JTI and mint its sole replacement under one row lock."""
    token = token_class(raw_refresh)
    jti = token.get(api_settings.JTI_CLAIM)
    if not jti:
        raise TokenError("Token has no id")

    with transaction.atomic():
        try:
            outstanding = OutstandingToken.objects.select_for_update().get(jti=jti)
        except OutstandingToken.DoesNotExist as exc:
            raise TokenError("Token is invalid") from exc
        if BlacklistedToken.objects.filter(token=outstanding).exists():
            raise TokenError("Token is blacklisted")

        context = validate(token)
        _blacklisted, created = BlacklistedToken.objects.get_or_create(
            token=outstanding
        )
        if not created:
            raise TokenError("Token is blacklisted")
        return mint(token, context)
