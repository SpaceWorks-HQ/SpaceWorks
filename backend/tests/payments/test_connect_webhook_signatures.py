"""The Stripe Connect webhook with a READABLE secret and a bad signature (cloud lane).

The existing fail-safe tests cover an unreadable secret. With a good secret configured,
every forged, stale, malformed or non-ASCII signature must still be the same generic 400
-- never a 500, never a hint about which check failed, and never the secret in a log.
"""

import hashlib
import hmac
import json
import logging
import time

import pytest
from cryptography.fernet import Fernet
from rest_framework.test import APIClient

from apps.payments.models import PlatformStripeConnectSettings

pytestmark = pytest.mark.django_db

SECRET = "whsec_connect_signing_secret_value"
GENERIC_ERROR = {"detail": "Invalid Stripe webhook signature."}
BODY = json.dumps({"id": "evt_1", "type": "account.updated", "data": {"object": {}}}).encode()


@pytest.fixture(autouse=True)
def _managed_with_secret(settings):
    settings.PLATFORM_DOMAIN_SUFFIX = ".managed.test"
    settings.API_CLIENT_ENC_KEY = Fernet.generate_key().decode()
    platform = PlatformStripeConnectSettings.load()
    platform.set_stripe_webhook_secret(SECRET)
    platform.save()


def _signature(timestamp, secret=SECRET, body=BODY):
    digest = hmac.new(secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={digest}"


def _post(signature):
    return APIClient().post(
        "/api/v1/webhooks/stripe/connect", BODY, content_type="application/json",
        HTTP_STRIPE_SIGNATURE=signature, HTTP_HOST="localhost",
    )


@pytest.mark.parametrize(
    "signature",
    [
        "invalid",
        "",
        "t=notanumber,v1=abc",
        _signature(int(time.time()), secret="whsec_someone_else"),
        "t=1,v1=éè",
    ],
    ids=["garbage", "empty", "bad-timestamp", "wrong-secret", "non-ascii"],
)
def test_a_bad_signature_is_the_generic_400(caplog, signature):
    with caplog.at_level(logging.DEBUG):
        response = _post(signature)

    assert response.status_code == 400
    assert response.data == GENERIC_ERROR
    assert SECRET not in caplog.text


def test_a_correctly_signed_but_stale_event_is_refused():
    stale = int(time.time()) - 3600  # beyond the SDK's five-minute tolerance

    response = _post(_signature(stale))

    assert response.status_code == 400
    assert response.data == GENERIC_ERROR
