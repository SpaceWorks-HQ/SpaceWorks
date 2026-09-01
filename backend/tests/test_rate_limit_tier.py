import hashlib
import hmac
import time

import pytest
from django.conf import settings as django_settings
from django.core.cache import cache
from django.test import override_settings
from rest_framework.test import APIClient

from apps.apiclients.models import ApiClient
from apps.apiclients.throttling import ClientTierRateThrottle
from tests.return_helpers import make_product, make_space

pytestmark = pytest.mark.django_db


THROTTLE_SETTINGS = {
    **django_settings.REST_FRAMEWORK,
    "DEFAULT_THROTTLE_RATES": {
        **django_settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"],
        "public_read": "1/min",
        "client_public": "1/min",
        "client_standard": "1/min",
        "client_trusted": "2/min",
    },
}

ORIGIN = "https://client.example"


@pytest.fixture(autouse=True)
def _clear_cache_and_rates(monkeypatch):
    cache.clear()
    monkeypatch.setattr(
        ClientTierRateThrottle,
        "THROTTLE_RATES",
        THROTTLE_SETTINGS["DEFAULT_THROTTLE_RATES"],
    )
    yield
    cache.clear()


def _public_inventory_url(makerspace):
    return f"/api/v1/public/{makerspace.slug}/inventory/"


def _public_inventory_space(slug):
    makerspace = make_space(slug)
    makerspace.public_inventory_enabled = True
    makerspace.enabled_modules = ["public_inventory"]
    makerspace.save(update_fields=["public_inventory_enabled", "enabled_modules"])
    make_product(makerspace, name=f"{slug} Product")
    return makerspace


def _issue_server_client(makerspace, *, tier):
    return ApiClient.issue(
        label=f"{tier} server client",
        makerspace=makerspace,
        allowed_origins=[ORIGIN],
        client_type="server",
        scopes=["public:read"],
        rate_limit_tier=tier,
    )


def _issue_browser_client(makerspace, *, tier):
    client, _secret = ApiClient.issue(
        label=f"{tier} browser client",
        makerspace=makerspace,
        allowed_origins=[ORIGIN],
        client_type="browser",
        scopes=["public:read"],
        rate_limit_tier=tier,
    )
    return client


def _signed_headers(api_client, secret, *, path, method="GET", body=b""):
    """Build the HMAC headers FrontendHMACMiddleware verifies for server clients."""
    timestamp = str(int(time.time()))
    message = b"\n".join([method.upper().encode(), path.encode(), timestamp.encode(), body])
    signature = hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()
    return {
        "HTTP_X_CLIENT_ID": api_client.client_id,
        "HTTP_X_TIMESTAMP": timestamp,
        "HTTP_X_SIGNATURE": signature,
        "HTTP_ORIGIN": ORIGIN,
    }


@override_settings(
    API_CLIENT_AUTH_REQUIRED=False,
    HMAC_PROTECTED_PATH_PREFIXES=["/api/public/", "/api/v1/public/"],
    REST_FRAMEWORK=THROTTLE_SETTINGS,
)
def test_verified_trusted_server_client_uses_higher_trusted_limit():
    makerspace = _public_inventory_space("trusted-tier")
    api_client, secret = _issue_server_client(makerspace, tier="trusted")
    url = _public_inventory_url(makerspace)
    client = APIClient()

    first = client.get(url, **_signed_headers(api_client, secret, path=url))
    second = client.get(url, **_signed_headers(api_client, secret, path=url))
    third = client.get(url, **_signed_headers(api_client, secret, path=url))

    assert first.status_code == 200
    assert second.status_code == 200  # client_trusted = 2/min
    assert third.status_code == 429


@override_settings(
    API_CLIENT_AUTH_REQUIRED=False,
    HMAC_PROTECTED_PATH_PREFIXES=["/api/public/", "/api/v1/public/"],
    REST_FRAMEWORK=THROTTLE_SETTINGS,
)
def test_verified_standard_server_client_uses_lower_standard_limit():
    makerspace = _public_inventory_space("standard-tier")
    api_client, secret = _issue_server_client(makerspace, tier="standard")
    url = _public_inventory_url(makerspace)
    client = APIClient()

    first = client.get(url, **_signed_headers(api_client, secret, path=url))
    second = client.get(url, **_signed_headers(api_client, secret, path=url))

    assert first.status_code == 200
    assert second.status_code == 429  # client_standard = 1/min


@override_settings(
    API_CLIENT_AUTH_REQUIRED=False,
    HMAC_PROTECTED_PATH_PREFIXES=["/api/public/", "/api/v1/public/"],
    REST_FRAMEWORK=THROTTLE_SETTINGS,
)
def test_spoofed_client_id_without_valid_signature_falls_back_to_public_read():
    # A forged X-Client-Id with no valid HMAC signature must NOT be granted the
    # trusted tier — it falls back to the anonymous public_read scope.
    makerspace = _public_inventory_space("spoofed-tier")
    api_client, _secret = _issue_server_client(makerspace, tier="trusted")
    url = _public_inventory_url(makerspace)
    client = APIClient()

    first = client.get(url, HTTP_X_CLIENT_ID=api_client.client_id)
    second = client.get(url, HTTP_X_CLIENT_ID=api_client.client_id)

    assert first.status_code == 200
    assert second.status_code == 429  # public_read = 1/min, not the trusted tier


@override_settings(
    API_CLIENT_AUTH_REQUIRED=False,
    HMAC_PROTECTED_PATH_PREFIXES=["/api/public/", "/api/v1/public/"],
    REST_FRAMEWORK=THROTTLE_SETTINGS,
)
def test_browser_client_id_and_origin_cannot_elevate_tier():
    # Browser clients are identified by public, forgeable client_id + Origin, so
    # they must never get an elevated tier even though access is allowed.
    makerspace = _public_inventory_space("browser-tier")
    api_client = _issue_browser_client(makerspace, tier="trusted")
    url = _public_inventory_url(makerspace)
    client = APIClient()
    headers = {"HTTP_X_CLIENT_ID": api_client.client_id, "HTTP_ORIGIN": ORIGIN}

    first = client.get(url, **headers)
    second = client.get(url, **headers)

    assert first.status_code == 200
    assert second.status_code == 429  # falls back to public_read = 1/min


@override_settings(
    API_CLIENT_AUTH_REQUIRED=False,
    HMAC_PROTECTED_PATH_PREFIXES=["/api/public/", "/api/v1/public/"],
    REST_FRAMEWORK=THROTTLE_SETTINGS,
)
def test_anonymous_traffic_still_uses_original_public_read_scope():
    makerspace = _public_inventory_space("anonymous-tier")
    url = _public_inventory_url(makerspace)
    client = APIClient()

    first = client.get(url)
    second = client.get(url)

    assert first.status_code == 200
    assert second.status_code == 429
