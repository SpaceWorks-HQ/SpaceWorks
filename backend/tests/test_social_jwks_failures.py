"""The JWKS fetch behind Google, Apple and OIDC sign-in, under provider failure (cloud lane).

Every way the key endpoint can misbehave must become `SocialProviderUnavailable` -- the
views turn that into a 503 "try again" -- and never escape as a 500. Two did escape before
this lane: a JSON body that is an array or scalar (`AttributeError` on `.get`), and a read
failure inside the streamed body, which is urllib3's error rather than requests'.
"""

import io
import json

import pytest
import requests
import urllib3
from django.core.cache import cache

from apps.accounts import social_jwt
from apps.accounts.social_jwt import SocialProviderUnavailable, _fetch_jwks

pytestmark = pytest.mark.django_db

URL = "https://idp.example/jwks"


class _Raw:
    def __init__(self, body=b"", error=None):
        self._body = io.BytesIO(body)
        self._error = error

    def read(self, size):
        if self._error is not None:
            raise self._error
        return self._body.read(size)


class _Response:
    def __init__(self, status=200, body=b"", headers=None, error=None):
        self.status_code = status
        self.headers = headers or {}
        self.raw = _Raw(body, error)


@pytest.fixture(autouse=True)
def _fresh_cache():
    cache.clear()
    yield
    cache.clear()


def _serve(monkeypatch, response=None, raises=None):
    calls = []

    def get(url, **kwargs):
        calls.append(kwargs)
        if raises is not None:
            raise raises
        return response

    monkeypatch.setattr(social_jwt.requests, "get", get)
    return calls


def test_a_good_key_set_is_returned_cached_and_fetched_without_redirects(monkeypatch, settings):
    keys = [{"kid": "k1", "kty": "RSA", "n": "x", "e": "AQAB"}]
    calls = _serve(monkeypatch, _Response(body=json.dumps({"keys": keys}).encode()))

    assert _fetch_jwks("google", URL, refresh=False) == keys
    assert _fetch_jwks("google", URL, refresh=False) == keys  # second read from cache
    assert len(calls) == 1
    assert calls[0]["allow_redirects"] is False
    assert calls[0]["timeout"] == settings.SOCIAL_AUTH_JWKS_TIMEOUT_SECONDS


@pytest.mark.parametrize(
    "response",
    [
        _Response(status=500),
        _Response(status=404),
        _Response(status=429),
        _Response(status=302),
        _Response(body=b"not json"),
        _Response(body=b"[]"),
        _Response(body=b'"a string"'),
        _Response(body=b'{"keys": "nope"}'),
        _Response(body=json.dumps({"keys": [{}] * 17}).encode()),
        _Response(headers={"Content-Length": str(10**9)}, body=b"{}"),
        _Response(error=urllib3.exceptions.ReadTimeoutError(None, URL, "read timed out")),
        _Response(error=urllib3.exceptions.ProtocolError("connection broken")),
    ],
    ids=[
        "500", "404", "429", "redirect", "not-json", "json-array", "json-scalar",
        "keys-not-list", "too-many-keys", "oversize-header", "read-timeout", "truncated",
    ],
)
def test_every_bad_answer_is_provider_unavailable(monkeypatch, response):
    _serve(monkeypatch, response)

    with pytest.raises(SocialProviderUnavailable):
        _fetch_jwks("google", URL, refresh=False)


def test_an_oversize_body_without_a_length_header_is_refused(monkeypatch, settings):
    body = b'{"keys": []' + b" " * (settings.SOCIAL_AUTH_JWKS_MAX_BYTES + 10) + b"}"
    _serve(monkeypatch, _Response(body=body))

    with pytest.raises(SocialProviderUnavailable):
        _fetch_jwks("google", URL, refresh=False)


@pytest.mark.parametrize(
    "error",
    [requests.Timeout("slow"), requests.ConnectionError("down"), requests.TooManyRedirects()],
    ids=["timeout", "connection", "redirects"],
)
def test_a_transport_failure_is_provider_unavailable(monkeypatch, error):
    _serve(monkeypatch, raises=error)

    with pytest.raises(SocialProviderUnavailable):
        _fetch_jwks("apple", URL, refresh=False)


def test_a_failed_fetch_caches_nothing(monkeypatch):
    _serve(monkeypatch, _Response(status=503))
    with pytest.raises(SocialProviderUnavailable):
        _fetch_jwks("google", URL, refresh=False)

    assert cache.get("social-jwks:google") is None
