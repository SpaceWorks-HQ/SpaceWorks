from decimal import Decimal

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import DeviceGrant
from apps.accounts.services_device_tokens import issue_device_token_pair
from apps.payments import stripe_client
from apps.payments.models import MakerspacePaymentSettings, Payment
from apps.payments.resolution import PaymentSource
from apps.payments.services import PaymentRailConflict, create_checkout_url, create_payment
from apps.payments.services_mobile import create_mobile_intent
from tests.device_helpers import make_native_app_registration
from tests.payments.test_machine_payments import service_request
from tests.return_helpers import make_member, make_space


pytestmark = pytest.mark.django_db


def configured_payment(makerspace, member):
    payment_settings, _ = MakerspacePaymentSettings.objects.get_or_create(
        makerspace=makerspace
    )
    payment_settings.stripe_publishable_key = "pk_test_mobile"
    payment_settings.set_stripe_secret_key("sk_test_mobile")
    payment_settings.set_stripe_webhook_secret("whsec_mobile")
    payment_settings.save()
    subject = service_request(makerspace, member)
    return create_payment(
        makerspace=makerspace,
        subject_type=Payment.SubjectType.MACHINE_SERVICE_REQUEST,
        subject_id=subject.pk,
        member=member,
        amount=Decimal("12.50"),
        currency="usd",
        created_by=member,
    )


def device_client(user, makerspace):
    now = timezone.now()
    grant = DeviceGrant.objects.create(
        registration=make_native_app_registration(),
        user=user,
        platform="apple",
        app_id="org.spaceworks.app",
        signing_identity="TEAM.org.spaceworks.app",
        environment="development",
        attestation_subject_fingerprint="f" * 64,
        attested_at=now,
        last_used_at=now,
    )
    access, _refresh, _family = issue_device_token_pair(user, grant)
    client = APIClient()
    client.credentials(
        HTTP_AUTHORIZATION=f"Bearer {access}",
        HTTP_X_MAKERSPACE_ID=str(makerspace.pk),
    )
    return client


def test_mobile_intent_is_idempotent_and_persists_no_client_secret(monkeypatch):
    makerspace = make_space("mobile-intent-idempotent")
    member = make_member("mobile-intent-idempotent-user", makerspace)
    payment = configured_payment(makerspace, member)
    create_calls = []

    def create_intent(source, *, idempotency_key, **params):
        create_calls.append((source, idempotency_key, params))
        return {"id": "pi_mobile_123", "client_secret": "pi_mobile_123_secret_value"}

    monkeypatch.setattr(stripe_client, "create_payment_intent", create_intent)
    monkeypatch.setattr(
        stripe_client,
        "retrieve_payment_intent",
        lambda source, intent_id: {
            "id": intent_id,
            "client_secret": "pi_mobile_123_secret_value",
        },
    )

    first = create_mobile_intent(payment.pk, actor=member)
    second = create_mobile_intent(payment.pk, actor=member)

    assert first == second == {
        "payment_id": payment.pk,
        "client_secret": "pi_mobile_123_secret_value",
        "publishable_key": "pk_test_mobile",
    }
    assert len(create_calls) == 1
    assert create_calls[0][1] == f"payment-mobile-intent-{payment.pk}"
    assert create_calls[0][2]["amount"] == 1250
    payment.refresh_from_db()
    assert payment.online_rail == Payment.OnlineRail.NATIVE_PAYMENT_INTENT
    assert payment.stripe_payment_intent_id == "pi_mobile_123"
    assert not hasattr(payment, "client_secret")


def test_checkout_and_native_payment_rails_are_mutually_exclusive(monkeypatch):
    makerspace = make_space("mobile-intent-rail")
    member = make_member("mobile-intent-rail-user", makerspace)
    payment = configured_payment(makerspace, member)
    monkeypatch.setattr(
        stripe_client,
        "create_payment_intent",
        lambda *args, **kwargs: {
            "id": "pi_native_rail",
            "client_secret": "pi_native_rail_secret",
        },
    )

    create_mobile_intent(payment.pk, actor=member)

    with pytest.raises(PaymentRailConflict):
        create_checkout_url(payment.pk)

    other = configured_payment(makerspace, member)
    other.online_rail = Payment.OnlineRail.CHECKOUT
    other.save(update_fields=["online_rail", "updated_at"])
    with pytest.raises(PaymentRailConflict):
        create_mobile_intent(other.pk, actor=member)


def test_mobile_endpoint_enforces_member_and_tenant_ownership(monkeypatch):
    makerspace = make_space("mobile-intent-owner")
    other_space = make_space("mobile-intent-other")
    member = make_member("mobile-intent-owner-user", makerspace)
    payment = configured_payment(makerspace, member)
    client = device_client(member, makerspace)
    monkeypatch.setattr(
        stripe_client,
        "create_payment_intent",
        lambda *args, **kwargs: {
            "id": "pi_owner",
            "client_secret": "pi_owner_secret",
        },
    )
    url = (
        f"/api/v1/member/makerspaces/{makerspace.pk}/payments/"
        f"{payment.pk}/mobile-intent"
    )

    response = client.post(url, format="json")

    assert response.status_code == 200
    assert response.data["payment_id"] == payment.pk
    assert "payment_intent_id" not in response.data
    escaped = client.post(
        f"/api/v1/member/makerspaces/{other_space.pk}/payments/"
        f"{payment.pk}/mobile-intent",
        format="json",
    )
    assert escaped.status_code == 403


def test_mobile_endpoint_sanitizes_provider_failure(monkeypatch):
    makerspace = make_space("mobile-intent-failure")
    member = make_member("mobile-intent-failure-user", makerspace)
    payment = configured_payment(makerspace, member)
    client = device_client(member, makerspace)
    monkeypatch.setattr(
        "apps.payments.views_member_mobile.create_mobile_intent",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            RuntimeError("provider secret diagnostic")
        ),
    )

    response = client.post(
        f"/api/v1/member/makerspaces/{makerspace.pk}/payments/"
        f"{payment.pk}/mobile-intent",
        format="json",
    )

    assert response.status_code == 503
    assert response.data == {
        "detail": "Payments are temporarily unavailable.",
        "code": "payments_unavailable",
    }


def test_connect_payment_intent_uses_direct_charge_account_and_fee(monkeypatch):
    calls = []

    class PaymentIntents:
        def create(self, *, params, options):
            calls.append((params, options))
            return {"id": "pi_connect"}

    client = type(
        "Client",
        (),
        {"v1": type("V1", (), {"payment_intents": PaymentIntents()})()},
    )()
    monkeypatch.setattr(stripe_client, "build_client", lambda source: client)
    source = PaymentSource(
        provider="connect",
        secret_key="sk_platform",
        webhook_secret="whsec_platform",
        publishable_key="pk_platform",
        connected_account_id="acct_mobile",
    )

    stripe_client.create_payment_intent(
        source,
        idempotency_key="payment-mobile-intent-99",
        amount=1000,
        currency="usd",
        application_fee_amount=75,
    )

    assert calls == [
        (
            {"amount": 1000, "currency": "usd", "application_fee_amount": 75},
            {
                "idempotency_key": "payment-mobile-intent-99",
                "stripe_account": "acct_mobile",
            },
        )
    ]
