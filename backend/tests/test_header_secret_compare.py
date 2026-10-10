"""Secrets presented in request headers are compared without ever raising (cloud lane).

`hmac.compare_digest` / `secrets.compare_digest` on two `str` arguments raise `TypeError`
when either holds a non-ASCII character. Three unauthenticated endpoints compared a header
that way, so any stranger could turn their 403/400 into a 500 -- and for the Razorpay
webhook a 500 also makes the provider retry. Each must answer exactly as it does for any
other wrong secret. The same file pins the API-key-request list's 400 on a non-integer
`?makerspace=`, which used to reach the ORM and 500.
"""

import pytest
from django.test import override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from apps.payments.models import ProcessedStripeEvent
from tests.payments.test_razorpay_provider import configure_razorpay, make_space, paid_body
from tests.return_helpers import authenticated_client, make_member

pytestmark = pytest.mark.django_db

NON_ASCII = "sécrèt-ü"


@override_settings(CRON_SECRET="the-real-cron-secret")
def test_cron_endpoint_treats_a_non_ascii_secret_as_a_plain_mismatch():
    response = APIClient().post(
        "/api/v1/internal/cron/return-reminders", HTTP_X_CRON_SECRET=NON_ASCII
    )
    assert response.status_code == 403


@override_settings(CRON_SECRET="the-real-cron-secret")
def test_cron_endpoint_still_accepts_the_right_secret():
    response = APIClient().post(
        "/api/v1/internal/cron/return-reminders",
        HTTP_X_CRON_SECRET="the-real-cron-secret",
    )
    assert response.status_code == 200


@override_settings(TELEGRAM_WEBHOOK_SECRET="the-real-telegram-secret")
def test_telegram_webhook_treats_a_non_ascii_secret_as_a_plain_mismatch():
    response = APIClient().post(
        "/api/v1/integrations/telegram/webhook",
        {"update_id": 1},
        format="json",
        HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN=NON_ASCII,
    )
    assert response.status_code == 403


@override_settings(TELEGRAM_WEBHOOK_SECRET="the-real-telegram-secret")
def test_telegram_webhook_still_acknowledges_the_right_secret():
    response = APIClient().post(
        "/api/v1/integrations/telegram/webhook",
        {"update_id": 1},
        format="json",
        HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN="the-real-telegram-secret",
    )
    assert response.status_code == 200


def test_razorpay_webhook_treats_a_non_ascii_signature_as_forged(client):
    space = make_space("razorpay-non-ascii")
    configure_razorpay(space)

    response = client.post(
        reverse("razorpay-webhook", args=[space.public_code]),
        data=paid_body(),
        content_type="application/json",
        HTTP_X_RAZORPAY_SIGNATURE=NON_ASCII,
    )

    assert response.status_code == 400
    assert not ProcessedStripeEvent.objects.exists()


def test_api_key_request_list_rejects_a_non_integer_makerspace_filter():
    from tests.return_helpers import make_space as make_plain_space

    space = make_plain_space("key-request-filter")
    staff = authenticated_client(make_member("key-request-filter-staff", space))

    bad = staff.get("/api/v1/admin/api-key-requests", {"makerspace": "abc"})
    good = staff.get("/api/v1/admin/api-key-requests", {"makerspace": str(space.pk)})

    assert bad.status_code == 400
    assert "makerspace" in bad.json()
    assert good.status_code == 200
