import hashlib
import hmac
import os
import time
from urllib.parse import urlsplit, urlunsplit

import pytest
from django.core.cache import caches
from django.test import override_settings
from rest_framework.test import APIClient

from apps.apiclients.models import ApiClient
from apps.inventory.middleware import LEGACY_NONCE_WARNING_EVENT, NONCE_MAX_LENGTH

pytestmark = pytest.mark.django_db

PUBLIC = "/api/v1/public/makerspaces/"
ORIGIN = "https://nonce-client.example"
VALID_NONCE = "qM4t4xY9_k2-Vp7sJ3w6Hg"
_MISSING = object()


@pytest.fixture(autouse=True)
def _hmac_settings(settings):
    settings.API_CLIENT_AUTH_REQUIRED = False
    settings.APICLIENT_REQUIRE_NONCE = False
    settings.HMAC_MAX_CLOCK_SKEW_SECONDS = 300
    settings.HMAC_PROTECTED_PATH_PREFIXES = ["/api/public/", "/api/v1/public/"]


@pytest.fixture
def server_client():
    return ApiClient.issue(
        label="nonce test client",
        allowed_origins=[ORIGIN],
        client_type="server",
    )


def _signed_headers(api_client, secret, *, nonce=_MISSING):
    timestamp = str(int(time.time()))
    parts = [b"GET", PUBLIC.encode(), timestamp.encode()]
    if nonce is not _MISSING:
        parts.append(nonce.encode())
    parts.append(b"")
    signature = hmac.new(
        secret.encode(), b"\n".join(parts), hashlib.sha256
    ).hexdigest()
    headers = {
        "HTTP_X_CLIENT_ID": api_client.client_id,
        "HTTP_X_TIMESTAMP": timestamp,
        "HTTP_X_SIGNATURE": signature,
        "HTTP_ORIGIN": ORIGIN,
    }
    if nonce is not _MISSING:
        headers["HTTP_X_NONCE"] = nonce
    return headers


def _redis_test_url():
    raw = (
        os.environ.get("CACHE_URL")
        or os.environ.get("CELERY_BROKER_URL")
        or "redis://localhost:6379/15"
    )
    parsed = urlsplit(raw)
    if parsed.scheme not in {"redis", "rediss"}:
        parsed = urlsplit("redis://localhost:6379/15")
    return urlunsplit(parsed._replace(path="/15"))


REPLAY_CACHE_CONFIGS = [
    pytest.param(
        {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": _redis_test_url(),
        },
        "RedisCache",
        id="redis",
    ),
    pytest.param(
        {
            "BACKEND": "django.core.cache.backends.db.DatabaseCache",
            "LOCATION": "spaceworks_cache",
            "OPTIONS": {"MAX_ENTRIES": 100_000},
        },
        "DatabaseCache",
        id="database",
    ),
]


@pytest.mark.parametrize("cache_config,backend_name", REPLAY_CACHE_CONFIGS)
def test_replayed_nonce_is_rejected_by_each_shared_cache_backend(
    server_client, cache_config, backend_name
):
    api_client, secret = server_client
    headers = _signed_headers(api_client, secret, nonce=VALID_NONCE)

    with override_settings(CACHES={"default": cache_config}):
        replay_cache = caches["default"]
        assert replay_cache.__class__.__name__ == backend_name

        first = APIClient().get(PUBLIC, **headers)
        second = APIClient().get(PUBLIC, **headers)

        assert abs(int(time.time()) - int(headers["HTTP_X_TIMESTAMP"])) < 300
        assert first.status_code == 200
        assert second.status_code == 401


def test_nonce_tampered_in_transit_fails_signature(server_client):
    api_client, secret = server_client
    headers = _signed_headers(api_client, secret, nonce=VALID_NONCE)
    headers["HTTP_X_NONCE"] = "zR8p2mW5-v7_Yk4nQ6s9Lg"

    assert APIClient().get(PUBLIC, **headers).status_code == 401
    headers["HTTP_X_NONCE"] = VALID_NONCE
    assert APIClient().get(PUBLIC, **headers).status_code == 200


def test_different_clients_may_use_the_same_nonce():
    first_client, first_secret = ApiClient.issue(
        label="first nonce client", allowed_origins=[ORIGIN], client_type="server"
    )
    second_client, second_secret = ApiClient.issue(
        label="second nonce client", allowed_origins=[ORIGIN], client_type="server"
    )

    first = APIClient().get(
        PUBLIC, **_signed_headers(first_client, first_secret, nonce=VALID_NONCE)
    )
    second = APIClient().get(
        PUBLIC, **_signed_headers(second_client, second_secret, nonce=VALID_NONCE)
    )

    assert first.status_code == 200
    assert second.status_code == 200


@pytest.mark.parametrize("nonce", ["x" * (NONCE_MAX_LENGTH + 1), "bad:nonce"])
def test_overlong_or_malformed_nonce_is_rejected(server_client, nonce):
    api_client, secret = server_client

    response = APIClient().get(
        PUBLIC, **_signed_headers(api_client, secret, nonce=nonce)
    )

    assert response.status_code == 401


def test_enforcement_off_accepts_and_logs_nonce_less_client(server_client, caplog):
    api_client, secret = server_client

    with caplog.at_level("WARNING", logger="apps.inventory.middleware"):
        response = APIClient().get(PUBLIC, **_signed_headers(api_client, secret))

    assert response.status_code == 200
    assert LEGACY_NONCE_WARNING_EVENT in caplog.messages
    record = next(
        r for r in caplog.records if r.getMessage() == LEGACY_NONCE_WARNING_EVENT
    )
    assert record.client_id == api_client.client_id


def test_enforcement_on_rejects_nonce_less_signed_client(server_client, settings):
    settings.APICLIENT_REQUIRE_NONCE = True
    api_client, secret = server_client

    response = APIClient().get(PUBLIC, **_signed_headers(api_client, secret))

    assert response.status_code == 401


def test_openapi_documents_api_client_nonce_header():
    response = APIClient().get("/schema/")

    assert response.status_code == 200
    schema = response.content.decode()
    assert "X-Nonce" in schema
    assert "APICLIENT_REQUIRE_NONCE" in schema
