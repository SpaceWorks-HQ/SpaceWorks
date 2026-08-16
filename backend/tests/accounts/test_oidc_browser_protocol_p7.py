import base64
import hashlib
import json
from datetime import timedelta
from urllib.parse import parse_qs, urlsplit

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from django.core.cache import cache
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import OidcBrowserAttempt, User
from apps.accounts.oidc_browser_http import OidcProviderUnavailable, discover
from apps.accounts.social_oidc import verify_oidc_token
from tests.accounts.oidc_browser_helpers import (
    ORIGIN,
    REDIRECT_URI,
    JsonResponse,
    make_provider,
    metadata,
    start,
)

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def oidc_settings(settings):
    settings.CORS_ALLOWED_ORIGINS = [ORIGIN]
    settings.AUTH_COOKIE_SECURE = False
    cache.clear()


def test_full_discovery_pkce_callback_and_session(monkeypatch):
    provider = make_provider()
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private_key.public_key()))
    jwk["kid"] = "browser-key"
    discovery = metadata(provider)

    def get(url, **kwargs):
        assert kwargs["allow_redirects"] is False
        if url == provider.jwks_url:
            return JsonResponse({"keys": [jwk]})
        assert url == f"{provider.issuer}/.well-known/openid-configuration"
        return JsonResponse(discovery)

    monkeypatch.setattr("apps.accounts.oidc_browser_http.requests.get", get)
    client = APIClient()
    started = start(client)
    assert started.status_code == 200, started.data
    query = parse_qs(urlsplit(started.data["authorization_url"]).query)
    assert query["code_challenge_method"] == ["S256"]
    attempt = OidcBrowserAttempt.objects.get()
    expected_challenge = base64.urlsafe_b64encode(
        hashlib.sha256(attempt.code_verifier.encode()).digest()
    ).rstrip(b"=").decode()
    assert query["code_challenge"] == [expected_challenge]
    assert attempt.code_verifier not in started.data["authorization_url"]

    now = timezone.now()
    token = jwt.encode(
        {
            "iss": provider.issuer,
            "aud": provider.client_id,
            "sub": "campus-subject",
            "iat": now,
            "exp": now + timedelta(minutes=5),
            "nonce": started.data["nonce"],
            "email": "new-member@example.test",
            "email_verified": True,
        },
        private_key,
        algorithm="RS256",
        headers={"kid": "browser-key"},
    )

    def post(url, *, data, **kwargs):
        assert url == discovery["token_endpoint"]
        assert kwargs["allow_redirects"] is False
        assert data["code_verifier"] == attempt.code_verifier
        assert data["redirect_uri"] == REDIRECT_URI
        return JsonResponse({"id_token": token})

    monkeypatch.setattr("apps.accounts.oidc_browser_http.requests.post", post)
    callback = client.post(
        "/api/v1/auth/social/oidc/callback",
        {"code": "authorization-code", "state": started.data["state"], "nonce": started.data["nonce"]},
        format="json",
        HTTP_ORIGIN=ORIGIN,
    )

    assert callback.status_code == 200, callback.data
    assert callback.data["access"]
    assert callback.cookies["refresh_token"].value
    assert User.objects.get(email="new-member@example.test").social_identities.get().provider == "oidc:campus"


@pytest.mark.parametrize("case", ["state", "expired", "origin", "consumed"])
def test_invalid_attempt_variants_are_refused(monkeypatch, case):
    provider = make_provider()
    monkeypatch.setattr(
        "apps.accounts.views_oidc_browser.discover", lambda _provider: metadata(provider)
    )
    started = start(APIClient())
    attempt = OidcBrowserAttempt.objects.get()
    state = started.data["state"]
    origin = ORIGIN
    if case == "state":
        state = "wrong-state"
    elif case == "expired":
        attempt.expires_at = timezone.now() - timedelta(seconds=1)
        attempt.save(update_fields=["expires_at"])
    elif case == "origin":
        origin = "http://127.0.0.1:5000"
    else:
        attempt.consumed_at = timezone.now()
        attempt.save(update_fields=["consumed_at"])

    response = APIClient().post(
        "/api/v1/auth/social/oidc/callback",
        {"code": "code", "state": state, "nonce": started.data["nonce"]},
        format="json",
        HTTP_ORIGIN=origin,
    )
    assert response.status_code == 401
    assert "refresh_token" not in response.cookies


def test_successful_state_cannot_be_replayed(monkeypatch):
    provider = make_provider()
    monkeypatch.setattr("apps.accounts.views_oidc_browser.discover", lambda _: metadata(provider))
    monkeypatch.setattr("apps.accounts.views_oidc_browser.exchange_code", lambda *a, **k: "id-token")
    monkeypatch.setattr(
        "apps.accounts.views_oidc_browser.verify_oidc_token",
        lambda *a, **k: {"sub": "sub", "email": "fresh@example.test", "email_verified": True},
    )
    started = start(APIClient())
    payload = {"code": "code", "state": started.data["state"], "nonce": started.data["nonce"]}
    first = APIClient().post("/api/v1/auth/social/oidc/callback", payload, format="json", HTTP_ORIGIN=ORIGIN)
    replay = APIClient().post("/api/v1/auth/social/oidc/callback", payload, format="json", HTTP_ORIGIN=ORIGIN)
    assert first.status_code == 200
    assert replay.status_code == 401
    assert "refresh_token" not in replay.cookies


def test_discovery_refuses_issuer_slash_redirect_size_and_slow(monkeypatch, settings):
    provider = make_provider()
    bad_documents = [
        JsonResponse(metadata(provider, issuer=f"{provider.issuer}/")),
        JsonResponse({}, status=302),
        JsonResponse({}, headers={"Content-Length": str(settings.OIDC_HTTP_MAX_BYTES + 1)}),
    ]
    for response in bad_documents:
        cache.clear()
        monkeypatch.setattr("apps.accounts.oidc_browser_http.requests.get", lambda *a, _r=response, **k: _r)
        with pytest.raises(OidcProviderUnavailable):
            discover(provider)

    cache.clear()
    monkeypatch.setattr("apps.accounts.oidc_browser_http.requests.get", lambda *a, **k: JsonResponse(metadata(provider)))
    ticks = iter((0.0, settings.OIDC_HTTP_TIMEOUT_SECONDS + 1.0))
    monkeypatch.setattr("apps.accounts.oidc_browser_http.time.monotonic", lambda: next(ticks))
    with pytest.raises(OidcProviderUnavailable):
        discover(provider)


def test_email_verified_is_literal_boolean_only(monkeypatch):
    provider = make_provider()
    monkeypatch.setattr(
        "apps.accounts.social_oidc.decode_rs256_token",
        lambda *a, **k: {"sub": "sub", "nonce": "nonce", "email": "member@example.test", "email_verified": "true"},
    )
    assert verify_oidc_token("token", nonce="nonce", provider_row=provider)["email_verified"] is False


def test_token_endpoint_oauth_error_is_an_explicit_rejection(monkeypatch):
    provider = make_provider()
    monkeypatch.setattr(
        "apps.accounts.views_oidc_browser.discover", lambda _: metadata(provider)
    )
    monkeypatch.setattr(
        "apps.accounts.oidc_browser_http.requests.post",
        lambda *a, **k: JsonResponse({"error": "invalid_grant"}, status=400),
    )
    started = start(APIClient())
    response = APIClient().post(
        "/api/v1/auth/social/oidc/callback",
        {"code": "bad-code", "state": started.data["state"], "nonce": started.data["nonce"]},
        format="json",
        HTTP_ORIGIN=ORIGIN,
    )
    assert response.status_code == 401
    assert response.data["code"] == "social_invalid"
    assert "refresh_token" not in response.cookies
