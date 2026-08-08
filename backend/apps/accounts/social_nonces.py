import hashlib
import hmac
import secrets
from datetime import timedelta
from urllib.parse import urlsplit

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.accounts.models_oidc import provider_for_slug, slug_from_provider_key
from apps.accounts.models_social import (
    PlatformSocialAuthSettings,
    SocialDelivery,
    SocialLoginNonce,
    SocialProvider,
    SocialSurface,
)
from apps.makerspaces.cors import (
    member_origin_is_registered,
    staff_origin_is_registered,
)
from apps.makerspaces.origin_scope import AMBIGUOUS_STAFF_ORIGIN_SCOPE, staff_origin_scope


class SocialAuthUnavailable(Exception):
    pass


class SocialNonceRejected(Exception):
    pass


def nonce_digest(raw):
    return hmac.new(settings.SECRET_KEY.encode(), raw.encode(), hashlib.sha256).hexdigest()


def request_origin(request):
    raw = request.headers.get("Origin") or request.headers.get("Referer", "")
    parts = urlsplit(raw)
    if not parts.scheme or not parts.netloc:
        return ""
    return f"{parts.scheme}://{parts.netloc}"


def provider_settings(provider, client_platform):
    # A generic OIDC provider carries its own configuration rather than living on the
    # platform singleton, so it is resolved before that row is even consulted -- a
    # deployment can run OIDC without ever configuring Google or Apple.
    oidc_slug = slug_from_provider_key(provider)
    if oidc_slug is not None:
        oidc_row = provider_for_slug(oidc_slug)
        if oidc_row is None:
            raise SocialAuthUnavailable
        return oidc_row, oidc_row.client_id

    row = PlatformSocialAuthSettings.objects.filter(pk=1).first()
    if row is None:
        raise SocialAuthUnavailable
    if provider == SocialProvider.GOOGLE:
        audience = row.client_id(provider, client_platform)
    elif provider == SocialProvider.APPLE:
        audience = (
            row.apple_service_id
            if client_platform == "web"
            else [item for item in row.apple_native_app_ids if isinstance(item, str)]
        )
    else:
        audience = ""
    if not audience:
        raise SocialAuthUnavailable
    return row, audience


def create_social_nonce(request, *, provider, surface, delivery, client_platform):
    provider_settings(provider, client_platform)
    origin = request_origin(request)
    grant = getattr(request, "device_grant", None)
    if delivery == SocialDelivery.WEB:
        if surface == SocialSurface.STAFF:
            if not staff_origin_is_registered(origin):
                raise SocialNonceRejected
            if staff_origin_scope(request) is AMBIGUOUS_STAFF_ORIGIN_SCOPE:
                raise SocialNonceRejected
        elif not member_origin_is_registered(origin):
            raise SocialNonceRejected
        grant = None
    else:
        if grant is None:
            raise SocialNonceRejected
        expected = "ios" if grant.platform == "apple" else "android"
        if client_platform != expected:
            raise SocialNonceRejected
        origin = ""
    raw = secrets.token_urlsafe(48)
    SocialLoginNonce.objects.create(
        provider=provider,
        surface=surface,
        delivery=delivery,
        client_platform=client_platform,
        nonce_digest=nonce_digest(raw),
        origin=origin,
        device_grant=grant,
        expires_at=timezone.now()
        + timedelta(seconds=settings.SOCIAL_AUTH_NONCE_TTL_SECONDS),
    )
    return raw


def consume_social_nonce(
    request, *, raw, provider, surface, delivery, client_platform
):
    now = timezone.now()
    with transaction.atomic():
        row = (
            SocialLoginNonce.objects.select_for_update()
            .filter(nonce_digest=nonce_digest(raw))
            .first()
        )
        valid = bool(
            row
            and row.consumed_at is None
            and row.expires_at > now
            and row.provider == provider
            and row.surface == surface
            and row.delivery == delivery
            and row.client_platform == client_platform
        )
        if row is not None and row.consumed_at is None:
            row.consumed_at = now
            row.save(update_fields=["consumed_at"])
    if not valid:
        raise SocialNonceRejected
    if delivery == SocialDelivery.WEB:
        if row.origin != request_origin(request):
            raise SocialNonceRejected
    elif row.device_grant_id != getattr(
        getattr(request, "device_grant", None), "pk", None
    ):
        raise SocialNonceRejected
    return row
