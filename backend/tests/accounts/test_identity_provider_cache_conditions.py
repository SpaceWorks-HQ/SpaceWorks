"""An optional cache cannot bypass token verification or break a fresh provider fetch."""

import io
import json
from datetime import datetime, UTC
from types import SimpleNamespace

import pytest

from apps.accounts import oidc_browser_http, social_jwt


class Response:
    status_code = 200
    headers = {}

    def __init__(self, payload):
        self.raw = io.BytesIO(json.dumps(payload).encode())
        self.closed = False

    def close(self):
        self.closed = True


@pytest.mark.parametrize("keys", [[None], ["key"], [[]]])
def test_non_object_jwks_keys_are_unavailable_and_connection_closed(monkeypatch, keys):
    response = Response({"keys": keys})
    monkeypatch.setattr(social_jwt.requests, "get", lambda *a, **k: response)
    with pytest.raises(social_jwt.SocialProviderUnavailable):
        social_jwt._fetch_jwks("malformed", "https://id.example/jwks", refresh=True)
    assert response.closed


def test_jwks_cache_outage_fetches_fresh_keys_and_closes_connection(monkeypatch):
    response = Response({"keys": [{"kid": "current", "kty": "RSA"}]})
    monkeypatch.setattr(social_jwt.requests, "get", lambda *a, **k: response)

    def unavailable(*a, **k):
        raise ConnectionError("private-cache-password")

    monkeypatch.setattr(social_jwt.cache, "get", unavailable)
    monkeypatch.setattr(social_jwt.cache, "set", unavailable)
    keys = social_jwt._fetch_jwks("google", "https://id.example/jwks", refresh=False)
    assert keys == [{"kid": "current", "kty": "RSA"}]
    assert response.closed


def test_key_rotation_refetches_when_the_cached_kid_is_absent(monkeypatch):
    seen = []

    def keys(provider, url, refresh):
        seen.append(refresh)
        return [{"kid": "new", "kty": "RSA"}] if refresh else [{"kid": "old", "kty": "RSA"}]

    monkeypatch.setattr(social_jwt, "_fetch_jwks", keys)
    monkeypatch.setattr(social_jwt.jwt, "get_unverified_header", lambda token: {"alg": "RS256", "kid": "new"})
    monkeypatch.setattr(social_jwt.jwt.algorithms.RSAAlgorithm, "from_jwk", lambda raw: "key")
    monkeypatch.setattr(social_jwt.jwt, "decode", lambda *a, **k: {"sub": "verified-user"})
    assert social_jwt.decode_rs256_token(
        "signed-token", provider="google", jwks_url="https://id.example/jwks", issuer="issuer", audience="app",
    ) == {"sub": "verified-user"}
    assert seen == [False, True]


def test_discovery_cache_outage_does_not_skip_issuer_validation(monkeypatch):
    provider = SimpleNamespace(pk=1, updated_at=datetime.now(UTC), issuer="https://id.example")
    payload = {
        "issuer": provider.issuer, "authorization_endpoint": "https://id.example/authorize",
        "token_endpoint": "https://id.example/token", "jwks_uri": "https://id.example/jwks",
    }
    response = Response(payload)
    monkeypatch.setattr(oidc_browser_http.requests, "get", lambda *a, **k: response)

    def unavailable(*a, **k):
        raise ConnectionError("private-cache-password")

    monkeypatch.setattr(oidc_browser_http.cache, "get", unavailable)
    monkeypatch.setattr(oidc_browser_http.cache, "set", unavailable)
    assert oidc_browser_http.discover(provider) == payload
    assert response.closed
