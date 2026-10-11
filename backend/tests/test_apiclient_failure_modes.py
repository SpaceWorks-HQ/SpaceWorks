"""HMAC verification under hostile or broken conditions (cloud-completeness lane).

The happy path, replay and rotation are pinned elsewhere. What was not pinned is the set of
conditions where the verifier itself is the thing under stress: a clock-skewed or garbage
timestamp, a stored secret that no longer decrypts (an `API_CLIENT_ENC_KEY` that changed
underneath the database), and a nonce cache that is down. Each must answer the same
generic 401 and never a 500 -- a 500 would both break the client and tell an attacker the
verifier fell over -- and a failure before the signature check must not burn the nonce.
"""

import hashlib
import hmac
import time

import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

from apps.apiclients.models import ApiClient
from apps.inventory import middleware_hmac as hmac_middleware

pytestmark = pytest.mark.django_db

PUBLIC_PATH = "/api/v1/public/makerspaces/"
ORIGIN = "https://failure-modes.example"


@pytest.fixture(autouse=True)
def _hmac_settings(settings):
    settings.API_CLIENT_AUTH_REQUIRED = True
    settings.APICLIENT_REQUIRE_NONCE = True
    settings.HMAC_MAX_CLOCK_SKEW_SECONDS = 300
    settings.HMAC_PROTECTED_PATH_PREFIXES = ["/api/public/", "/api/v1/public/"]
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def server_client():
    return ApiClient.issue(
        label="failure-mode client",
        allowed_origins=[ORIGIN],
        client_type="server",
        scopes=["public:read"],
    )


def _headers(api_client, secret, *, nonce, timestamp=None):
    timestamp = str(int(time.time())) if timestamp is None else timestamp
    message = b"\n".join(
        [b"GET", PUBLIC_PATH.encode(), timestamp.encode(), nonce.encode(), b""]
    )
    return {
        "HTTP_X_CLIENT_ID": api_client.client_id,
        "HTTP_X_TIMESTAMP": timestamp,
        "HTTP_X_SIGNATURE": hmac.new(secret.encode(), message, hashlib.sha256).hexdigest(),
        "HTTP_X_NONCE": nonce,
        "HTTP_ORIGIN": ORIGIN,
    }


def test_a_correct_signature_passes_as_the_control(server_client):
    api_client, secret = server_client
    response = APIClient().get(PUBLIC_PATH, **_headers(api_client, secret, nonce="control-nonce-1"))
    assert response.status_code == 200


@pytest.mark.parametrize("offset", [-301, 301, -86_400, 86_400])
def test_a_timestamp_outside_the_skew_window_is_refused(server_client, offset):
    api_client, secret = server_client
    stale = str(int(time.time()) + offset)
    response = APIClient().get(
        PUBLIC_PATH, **_headers(api_client, secret, nonce=f"skew-{offset}", timestamp=stale)
    )
    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid client signature."}


@pytest.mark.parametrize("timestamp", ["not-a-number", "1.5", "", " "])
def test_a_malformed_timestamp_is_refused_not_500(server_client, timestamp):
    api_client, secret = server_client
    response = APIClient().get(
        PUBLIC_PATH, **_headers(api_client, secret, nonce="bad-ts", timestamp=timestamp)
    )
    assert response.status_code == 401


def test_a_skewed_request_does_not_consume_its_nonce(server_client):
    """The nonce is claimed only after the signature verifies, so a refused request
    cannot be used to poison a nonce the real client is about to send."""
    api_client, secret = server_client
    stale = str(int(time.time()) - 10_000)
    refused = APIClient().get(
        PUBLIC_PATH, **_headers(api_client, secret, nonce="shared-nonce", timestamp=stale)
    )
    accepted = APIClient().get(PUBLIC_PATH, **_headers(api_client, secret, nonce="shared-nonce"))
    assert (refused.status_code, accepted.status_code) == (401, 200)


def test_an_undecryptable_stored_secret_fails_closed_with_401(server_client):
    """An `API_CLIENT_ENC_KEY` change leaves ciphertext the box can no longer read."""
    api_client, secret = server_client
    ApiClient.objects.filter(pk=api_client.pk).update(secret_encrypted=b"gAAAAA-not-a-token")
    response = APIClient().get(PUBLIC_PATH, **_headers(api_client, secret, nonce="enc-key-gone"))
    assert response.status_code == 401


def test_a_nonce_cache_outage_fails_closed_with_401(server_client, monkeypatch):
    """Redis down must not turn replay protection off: no claim, no request."""
    api_client, secret = server_client

    def cache_down(*args, **kwargs):
        raise ConnectionError("cache unavailable")

    monkeypatch.setattr(hmac_middleware, "claim_nonce", cache_down)
    response = APIClient().get(PUBLIC_PATH, **_headers(api_client, secret, nonce="cache-down"))
    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid client signature."}


def test_a_signature_for_another_path_is_refused(server_client):
    api_client, secret = server_client
    headers = _headers(api_client, secret, nonce="other-path")
    response = APIClient().get("/api/v1/public/makerspaces/?page=2", **headers)
    assert response.status_code == 401
