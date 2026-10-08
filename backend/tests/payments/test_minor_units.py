"""Provider amounts are the currency's smallest unit, which is not always a hundredth."""

from decimal import Decimal

import pytest

from apps.makerspaces.models import MakerspaceMembership
from apps.payments import stripe_client
from apps.payments.models import Payment, Refund
from apps.payments.money import to_minor_units
from apps.payments.services import _application_fee_amount, create_checkout_url
from apps.payments.services_mobile import _intent_params
from apps.payments.services_refunds import refund_payment
from tests.payments.test_models import configured_settings
from tests.payments.test_refunds import paid_deposit, stripe_space
from tests.return_helpers import enable_online_rail, make_member, make_space


@pytest.mark.parametrize(
    ("amount", "currency", "expected"),
    [
        ("12.50", "usd", 1250),
        ("12.50", "INR", 1250),
        ("1500.00", "jpy", 1500),
        ("990", "krw", 990),
        ("1.25", "kwd", 1250),
        ("0.01", "eur", 1),
    ],
)
def test_minor_units_follow_the_currency_exponent(amount, currency, expected):
    assert to_minor_units(Decimal(amount), currency) == expected


def test_the_platform_fee_is_taken_in_the_currency_minor_unit():
    # 10% of 1500 yen is 150 yen, not 15000.
    assert _application_fee_amount(Decimal("1500.00"), 1000, "jpy") == 150
    assert _application_fee_amount(Decimal("12.50"), 100, "usd") == 13


def _yen_debt(slug):
    space = make_space(slug)
    enable_online_rail(space, "membership")
    configured_settings(space)
    member = make_member(f"{slug}-member", space)
    membership = MakerspaceMembership.objects.get(makerspace=space, user=member)
    return Payment.objects.create(
        makerspace=space,
        subject_type=Payment.SubjectType.MAKERSPACE_MEMBERSHIP,
        subject_id=membership.pk,
        member=member,
        amount=Decimal("1500.00"),
        currency="jpy",
        created_by=member,
    )


@pytest.mark.django_db
def test_a_yen_checkout_charges_1500_yen_not_150000(monkeypatch):
    payment = _yen_debt("minor-units-checkout")
    sent = []
    monkeypatch.setattr(
        "apps.payments.services_checkout.member_payment_return_url",
        lambda _space: "https://space.example/member",
    )
    monkeypatch.setattr(
        "apps.payments.services_checkout.stripe_client.create_checkout_session",
        lambda _source, **params: sent.append(params) or {"id": "cs_jpy", "url": "https://checkout.stripe.test/jpy"},
    )

    create_checkout_url(payment.pk)

    assert sent[0]["line_items"][0]["price_data"]["unit_amount"] == 1500


@pytest.mark.django_db
def test_a_yen_native_intent_charges_1500_yen():
    payment = _yen_debt("minor-units-intent")
    assert _intent_params(payment)["amount"] == 1500


@pytest.mark.django_db
def test_a_yen_refund_sends_the_yen_amount(monkeypatch):
    makerspace, staff = stripe_space(
        "minor-units-refund", monkeypatch, [{"id": "re_jpy", "status": "succeeded"}]
    )
    payment = paid_deposit(makerspace, staff, amount="1500.00")
    Payment.objects.filter(pk=payment.pk).update(currency="jpy")
    payment.refresh_from_db()
    captured = []
    real = stripe_client.create_refund

    def spy(source, **params):
        captured.append(params)
        return real(source, **params)

    monkeypatch.setattr(stripe_client, "create_refund", spy)

    refund = refund_payment(payment, amount=Decimal("500"), reason="", actor=staff)

    assert captured[0]["amount"] == 500
    assert refund.status == Refund.Status.SUCCEEDED
