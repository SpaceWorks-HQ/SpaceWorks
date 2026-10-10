"""Attested push registration refuses unavailable hashing, other owners and floods."""

import pytest

from apps.integrations.models_push import PushDevice
from tests.return_helpers import make_member, make_space
from tests.test_native_push import device_client

pytestmark = pytest.mark.django_db
URL = "/api/v1/integrations/push/devices"
PAYLOAD = {"token": "a" * 64, "provider": "apns", "environment": "development"}


def test_missing_fingerprint_key_returns_503_and_creates_no_device(settings):
    settings.PUSH_TOKEN_HMAC_KEY = ""
    space = make_space("push-no-hmac")
    client, _ = device_client(make_member("push-no-hmac-user", space), space)
    assert client.post(URL, PAYLOAD, format="json").status_code == 503
    assert not PushDevice.objects.exists()


def test_another_account_cannot_claim_the_same_token(settings):
    settings.PUSH_TOKEN_HMAC_KEY = "h" * 64
    space = make_space("push-owner-conflict")
    owner = make_member("push-owner", space)
    other = make_member("push-other", space)
    first, _ = device_client(owner, space)
    second, _ = device_client(other, space)
    assert first.post(URL, PAYLOAD, format="json").status_code == 201
    assert second.post(URL, PAYLOAD, format="json").status_code == 409
    assert PushDevice.objects.get().user_id == owner.pk


def test_push_registration_rate_limit_returns_429(settings, monkeypatch):
    from rest_framework.throttling import ScopedRateThrottle

    settings.PUSH_TOKEN_HMAC_KEY = "h" * 64
    monkeypatch.setattr(ScopedRateThrottle, "THROTTLE_RATES", {
        **ScopedRateThrottle.THROTTLE_RATES, "push_device_registration": "1/min",
    })
    space = make_space("push-rate")
    client, _ = device_client(make_member("push-rate-user", space), space)
    assert client.post(URL, PAYLOAD, format="json").status_code == 201
    assert client.post(URL, PAYLOAD, format="json").status_code == 429
