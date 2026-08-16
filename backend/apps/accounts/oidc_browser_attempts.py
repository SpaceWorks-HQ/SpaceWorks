"""Create and consume three-secret OIDC browser attempts."""

import base64
import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import timedelta
from urllib.parse import urlencode, urlsplit

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import OidcBrowserAttempt
from apps.accounts.models_oidc import provider_key
from apps.accounts.social_nonces import request_origin
from apps.audit import services as audit
from apps.makerspaces.cors import member_origin_is_registered
from apps.makerspaces.models import MakerspaceMembership
from apps.makerspaces.servability import servable_queryset


class OidcAttemptRejected(Exception):
    pass


@dataclass(frozen=True, slots=True)
class StartedOidcAttempt:
    authorization_url: str
    state: str
    nonce: str


def start_attempt(request, provider, document, *, redirect_uri, email="", makerspace_slug=""):
    origin = request_origin(request)
    if not member_origin_is_registered(origin) or not _valid_redirect(redirect_uri, origin):
        raise OidcAttemptRejected()
    state = secrets.token_urlsafe(48)
    nonce = secrets.token_urlsafe(48)
    verifier = secrets.token_urlsafe(64)
    user_id, membership_id = _transition_binding(
        request, email=email, makerspace_slug=makerspace_slug
    )
    with transaction.atomic():
        attempt = OidcBrowserAttempt.objects.create(
            provider=provider.provider_key,
            state_digest=_digest("state", state),
            nonce_digest=_digest("nonce", nonce),
            code_verifier=verifier,
            redirect_uri=redirect_uri,
            origin=origin,
            intended_user_id=user_id,
            intended_membership_id=membership_id,
            expires_at=timezone.now() + timedelta(seconds=settings.OIDC_ATTEMPT_TTL_SECONDS),
        )
        actor = request.user if getattr(request.user, "is_authenticated", False) else None
        audit.record(
            actor,
            "auth.oidc_browser_attempt_started",
            target=attempt,
            meta={"provider": provider.provider_key, "transition": bool(user_id)},
        )
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b"=").decode()
    query = urlencode(
        {
            "response_type": "code",
            "client_id": provider.client_id,
            "redirect_uri": redirect_uri,
            "scope": "openid email profile",
            "state": state,
            "nonce": nonce,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
    )
    separator = "&" if "?" in document["authorization_endpoint"] else "?"
    return StartedOidcAttempt(
        authorization_url=f"{document['authorization_endpoint']}{separator}{query}",
        state=state,
        nonce=nonce,
    )


def consume_attempt(request, *, state, nonce):
    now = timezone.now()
    failure = None
    resolved = None
    with transaction.atomic():
        row = (
            OidcBrowserAttempt.objects.select_for_update()
            .filter(state_digest=_digest("state", state))
            .first()
        )
        valid = bool(
            row
            and row.consumed_at is None
            and row.expires_at > now
            and row.origin == request_origin(request)
            and hmac.compare_digest(row.nonce_digest, _digest("nonce", nonce))
        )
        if row is not None and row.consumed_at is None:
            row.consumed_at = now
            row.save(update_fields=["consumed_at"])
            audit.record(
                None,
                "auth.oidc_browser_attempt_consumed",
                target=row,
                meta={
                    "provider": row.provider,
                    "outcome": "accepted" if valid else "refused",
                },
            )
        if valid:
            resolved = row
        else:
            failure = OidcAttemptRejected()
    if failure is not None:
        raise failure
    return resolved


def _transition_binding(request, *, email, makerspace_slug):
    claim = getattr(request, "claim_session", None)
    if claim is not None:
        return claim.membership.user_id, claim.membership_id
    normalized = (email or "").strip().lower()
    slug = (makerspace_slug or "").strip()
    if not normalized or not slug:
        return None, None
    membership = (
        servable_queryset(MakerspaceMembership.objects.filter(
            makerspace__slug=slug,
            status="active",
            user__email__iexact=normalized,
            user__is_walk_in=True,
        ), relation="makerspace")
        .select_related("user")
        .first()
    )
    return (None, None) if membership is None else (membership.user_id, membership.pk)


def _valid_redirect(value, origin):
    if not isinstance(value, str) or len(value) > 2048:
        return False
    parsed = urlsplit(value)
    candidate = f"{parsed.scheme}://{parsed.netloc}"
    return bool(
        parsed.scheme
        and parsed.netloc
        and parsed.username is None
        and parsed.password is None
        and not parsed.fragment
        and candidate == origin
        and (parsed.scheme == "https" or parsed.hostname in {"localhost", "127.0.0.1", "::1"})
    )


def _digest(role, raw):
    return hmac.new(
        settings.SECRET_KEY.encode(),
        f"oidc-browser:{role}:v1\0{raw}".encode(),
        hashlib.sha256,
    ).hexdigest()
