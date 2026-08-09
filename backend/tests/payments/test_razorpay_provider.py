"""Razorpay as a second payment provider (phase 4).

Tests external behaviour: what a makerspace can configure, what the webhook accepts and
refuses, and which invariants survive a second vendor. The HTTP layer is stubbed -- the
point is the discipline around the call, not that urllib works.
"""

import hashlib
import hmac
import json
from decimal import Decimal

import pytest
from django.urls import reverse

from apps.makerspaces.models import Makerspace
from apps.payments.models import MakerspacePaymentSettings, Payment, ProcessedStripeEvent
from apps.payments.providers import get_provider
from apps.payments.providers.base import (
    CheckoutRequest,
    PaymentsUnavailable,
    WebhookVerificationError,
)
from apps.payments.resolution import resolve_payment_source

pytestmark = pytest.mark.django_db

WEBHOOK_SECRET = "rzp_webhook_secret"


def make_space(slug="razorpay-space"):
    return Makerspace.objects.create(name=slug, slug=slug)


def configure_razorpay(space, *, webhook_secret=WEBHOOK_SECRET):
    row = MakerspacePaymentSettings(makerspace=space, provider="razorpay")
    row.razorpay_key_id = "rzp_test_key"
    row.set_razorpay_key_secret("rzp_test_secret")
    row.set_razorpay_webhook_secret(webhook_secret)
    row.save()
    return row


def sign(body: bytes, secret=WEBHOOK_SECRET):
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def paid_body(link_id="plink_1", payment_id="pay_1", payment_pk=1):
    return json.dumps(
        {
            "event": "payment_link.paid",
            "payload": {
                "payment_link": {"entity": {"id": link_id, "notes": {"payment_id": str(payment_pk)}}},
                "payment": {"entity": {"id": payment_id}},
            },
        }
    ).encode()


# --- configuration ----------------------------------------------------------


def test_a_space_is_not_configured_until_every_razorpay_credential_is_present():
    space = make_space()
    row = MakerspacePaymentSettings(makerspace=space, provider="razorpay")
    row.razorpay_key_id = "rzp_test_key"
    row.save()

    assert row.raw_credentials_configured is False
    assert resolve_payment_source(space) is None


def test_leftover_stripe_keys_do_not_make_a_razorpay_space_look_configured():
    # The dangerous direction: a space that switches to Razorpay but still holds old
    # Stripe keys must not read as configured, or it would raise a checkout against a
    # vendor it no longer uses.
    space = make_space()
    row = MakerspacePaymentSettings(makerspace=space, provider="razorpay")
    row.set_stripe_secret_key("sk_test_leftover")
    row.set_stripe_webhook_secret("whsec_leftover")
    row.save()

    assert row.raw_credentials_configured is False
    assert resolve_payment_source(space) is None


def test_a_configured_space_resolves_a_razorpay_source():
    space = make_space()
    configure_razorpay(space)

    source = resolve_payment_source(space)

    assert source is not None
    assert source.vendor == "razorpay"
    # key_id is public and rides in the publishable slot, so one resolution path serves
    # both vendors rather than a parallel Razorpay-shaped source object.
    assert source.publishable_key == "rzp_test_key"
    assert source.secret_key == "rzp_test_secret"


# --- webhook verification ---------------------------------------------------


def test_webhook_rejects_a_forged_signature(client):
    space = make_space()
    configure_razorpay(space)
    body = paid_body()

    response = client.post(
        reverse("razorpay-webhook", args=[space.public_code]),
        data=body,
        content_type="application/json",
        HTTP_X_RAZORPAY_SIGNATURE="deadbeef",
    )

    assert response.status_code == 400
    assert not ProcessedStripeEvent.objects.exists()


def test_webhook_rejects_a_missing_signature(client):
    space = make_space()
    configure_razorpay(space)

    response = client.post(
        reverse("razorpay-webhook", args=[space.public_code]),
        data=paid_body(),
        content_type="application/json",
    )

    assert response.status_code == 400


def test_webhook_signature_is_computed_over_the_exact_bytes_received():
    # Signing a re-serialised body is the classic way to make a webhook check useless:
    # any whitespace or key-order difference changes the digest.
    space = make_space()
    configure_razorpay(space)
    source = resolve_payment_source(space)
    # Deliberately irregular spacing: re-serialising this changes the digest.
    body = b'{"event": "payment_link.paid",  "payload": {}}'

    event = get_provider("razorpay").verify_webhook(
        source, payload=body, headers={"X-Razorpay-Signature": sign(body)}
    )

    assert event.is_paid is True
    with pytest.raises(WebhookVerificationError):
        get_provider("razorpay").verify_webhook(
            source,
            payload=json.dumps(json.loads(body)).encode(),
            headers={"X-Razorpay-Signature": sign(body)},
        )


def test_an_authorised_but_uncaptured_payment_is_not_treated_as_paid():
    space = make_space()
    configure_razorpay(space)
    source = resolve_payment_source(space)
    body = json.dumps({"event": "payment.authorized", "payload": {}}).encode()

    event = get_provider("razorpay").verify_webhook(
        source, payload=body, headers={"X-Razorpay-Signature": sign(body)}
    )

    # The money has not moved yet; settling here would mark a charge complete for funds
    # that can still fail to arrive.
    assert event.is_paid is False


def test_a_razorpay_callback_to_a_stripe_space_is_refused(client):
    space = make_space()
    MakerspacePaymentSettings.objects.create(makerspace=space, provider="stripe")
    body = paid_body()

    response = client.post(
        reverse("razorpay-webhook", args=[space.public_code]),
        data=body,
        content_type="application/json",
        HTTP_X_RAZORPAY_SIGNATURE=sign(body),
    )

    assert response.status_code == 400


# --- settlement -------------------------------------------------------------


def make_payment(space, user, *, provider=Payment.Provider.RAZORPAY, order_id="plink_1"):
    return Payment.objects.create(
        makerspace=space,
        subject_type=Payment.SubjectType.BOOKING,
        subject_id=0,
        amount=Decimal("10.00"),
        currency="inr",
        created_by=user,
        provider=provider,
        external_order_id=order_id,
    )


def test_a_verified_paid_event_settles_the_matching_payment(client, django_user_model):
    space = make_space()
    configure_razorpay(space)
    user = django_user_model.objects.create_user(username="staff", password="x")
    payment = make_payment(space, user)
    body = paid_body(payment_pk=payment.pk)

    response = client.post(
        reverse("razorpay-webhook", args=[space.public_code]),
        data=body,
        content_type="application/json",
        HTTP_X_RAZORPAY_SIGNATURE=sign(body),
        HTTP_X_RAZORPAY_EVENT_ID="evt_1",
    )

    payment.refresh_from_db()
    assert response.status_code == 200
    assert payment.status == Payment.Status.PAID_ONLINE
    assert payment.external_payment_id == "pay_1"


def test_replaying_the_same_event_settles_only_once(client, django_user_model):
    space = make_space()
    configure_razorpay(space)
    user = django_user_model.objects.create_user(username="staff", password="x")
    payment = make_payment(space, user)
    body = paid_body(payment_pk=payment.pk)
    post = lambda: client.post(  # noqa: E731
        reverse("razorpay-webhook", args=[space.public_code]),
        data=body,
        content_type="application/json",
        HTTP_X_RAZORPAY_SIGNATURE=sign(body),
        HTTP_X_RAZORPAY_EVENT_ID="evt_1",
    )

    post()
    post()

    assert ProcessedStripeEvent.objects.filter(makerspace=space).count() == 1


def test_two_providers_may_use_the_same_event_id(django_user_model):
    # Without the provider column in the idempotency key the second vendor's event
    # would be swallowed as a duplicate and a real charge would never settle.
    space = make_space()
    ProcessedStripeEvent.objects.create(makerspace=space, provider="stripe", stripe_event_id="evt_shared")

    ProcessedStripeEvent.objects.create(makerspace=space, provider="razorpay", stripe_event_id="evt_shared")

    assert ProcessedStripeEvent.objects.filter(stripe_event_id="evt_shared").count() == 2


def test_a_paid_event_for_a_terminal_payment_is_audited_not_reapplied(client, django_user_model):
    from apps.audit.models import AuditLog

    space = make_space()
    configure_razorpay(space)
    user = django_user_model.objects.create_user(username="staff", password="x")
    payment = make_payment(space, user)
    Payment.objects.filter(pk=payment.pk).update(status=Payment.Status.PAID_OFFLINE)
    body = paid_body(payment_pk=payment.pk)

    client.post(
        reverse("razorpay-webhook", args=[space.public_code]),
        data=body,
        content_type="application/json",
        HTTP_X_RAZORPAY_SIGNATURE=sign(body),
        HTTP_X_RAZORPAY_EVENT_ID="evt_late",
    )

    payment.refresh_from_db()
    assert payment.status == Payment.Status.PAID_OFFLINE
    assert AuditLog.objects.filter(action="payment.paid_after_terminal").exists()


# --- invariants that survive a second vendor --------------------------------


def test_the_provider_is_immutable_once_the_row_exists(django_user_model):
    space = make_space()
    user = django_user_model.objects.create_user(username="staff", password="x")
    payment = make_payment(space, user)

    payment.provider = Payment.Provider.STRIPE
    with pytest.raises(Exception, match="provenance is immutable"):
        payment.save()


def test_one_payment_per_subject_is_unchanged_by_the_provider_column(django_user_model):
    from django.core.exceptions import ValidationError

    space = make_space()
    user = django_user_model.objects.create_user(username="staff", password="x")
    make_payment(space, user, order_id="plink_a")

    # Adding a provider column must not let a subject collect a second charge, one per
    # vendor. `Payment.save()` full_cleans, so the unique constraint surfaces as a
    # ValidationError before it ever reaches the database.
    with pytest.raises(ValidationError):
        Payment.objects.create(
            makerspace=space,
            subject_type=Payment.SubjectType.BOOKING,
            subject_id=0,
            amount=Decimal("5.00"),
            currency="inr",
            created_by=user,
            provider=Payment.Provider.STRIPE,
        )


def test_two_vendors_may_mint_the_same_external_order_id(django_user_model):
    space = make_space()
    user = django_user_model.objects.create_user(username="staff", password="x")
    make_payment(space, user, order_id="shared_id")

    Payment.objects.create(
        makerspace=space,
        subject_type=Payment.SubjectType.EVENT_REGISTRATION,
        subject_id=0,
        amount=Decimal("5.00"),
        currency="usd",
        created_by=user,
        provider=Payment.Provider.STRIPE,
        external_order_id="shared_id",
    )

    assert Payment.objects.filter(external_order_id="shared_id").count() == 2


# --- checkout ---------------------------------------------------------------


def test_checkout_sends_integer_minor_units_and_an_uppercase_currency(monkeypatch):
    space = make_space()
    configure_razorpay(space)
    source = resolve_payment_source(space)
    sent = {}

    def fake_request(self, src, method, path, body=None):
        sent.update({"path": path, "body": body})
        return {"id": "plink_x", "short_url": "https://rzp.io/i/x"}

    monkeypatch.setattr(
        "apps.payments.providers.razorpay.RazorpayProvider._request", fake_request
    )

    result = get_provider("razorpay").create_checkout(
        source,
        CheckoutRequest(
            amount_minor=1050,
            currency="inr",
            description="Laser time",
            reference="7",
            success_url="https://example.test/member?checkout=success",
            cancel_url="https://example.test/member?checkout=cancelled",
            metadata={"payment_id": 7},
            idempotency_key="k",
        ),
    )

    assert result.checkout_url == "https://rzp.io/i/x"
    assert sent["body"]["amount"] == 1050
    assert isinstance(sent["body"]["amount"], int)
    assert sent["body"]["currency"] == "INR"
    # We already mail members through the notification matrix; a second unmanaged
    # channel would bypass every recipient rule and module gate.
    assert sent["body"]["notify"] == {"sms": False, "email": False}


def test_a_checkout_failure_raises_payments_unavailable_not_a_vendor_error(monkeypatch):
    space = make_space()
    configure_razorpay(space)
    source = resolve_payment_source(space)

    def boom(self, src, method, path, body=None):
        raise PaymentsUnavailable("Razorpay could not be reached.")

    monkeypatch.setattr(
        "apps.payments.providers.razorpay.RazorpayProvider._request", boom
    )

    # Callers treat this as "no checkout yet", never as "the domain action failed" --
    # machine complete()/collect() must still succeed.
    with pytest.raises(PaymentsUnavailable):
        get_provider("razorpay").create_checkout(
            source,
            CheckoutRequest(
                amount_minor=100, currency="inr", description="x", reference="1",
                success_url="https://e.test/s", cancel_url="https://e.test/c",
                metadata={}, idempotency_key="k",
            ),
        )


def test_an_unknown_provider_key_raises_rather_than_defaulting_to_stripe():
    # Guessing would be how money ends up in the wrong merchant account.
    with pytest.raises(PaymentsUnavailable):
        get_provider("paypal")
