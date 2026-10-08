"""`provider=unclaimed`: a debt raised with no gateway is claimed exactly once.

The model guard and trigger 0015 both shipped in 773f98c4, but no test ever claimed a row,
so neither the claim nor the refusal of a second one was pinned.
"""

from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import DatabaseError, transaction
from rest_framework.test import APIClient

from apps.makerspaces.models import MakerspaceMembership
from apps.payments.models import Payment
from apps.payments.providers.razorpay import RazorpayProvider
from apps.payments.services import create_payment
from tests.payments.test_models import configured_settings
from tests.payments.test_razorpay_provider import configure_razorpay
from tests.return_helpers import enable_online_rail, make_member, make_space

pytestmark = pytest.mark.django_db


def _unclaimed_debt(slug):
    space = make_space(slug)
    enable_online_rail(space, "membership")
    member = make_member(f"{slug}-member", space)
    membership = MakerspaceMembership.objects.get(makerspace=space, user=member)
    payment = create_payment(
        makerspace=space,
        subject_type=Payment.SubjectType.MAKERSPACE_MEMBERSHIP,
        subject_id=membership.pk,
        member=member,
        amount=Decimal("20.00"),
        currency="usd",
        created_by=member,
    )
    assert payment.provider == Payment.Provider.UNCLAIMED
    return space, member, payment


def _checkout(space, member, payment):
    client = APIClient()
    client.force_authenticate(member)
    return client.post(f"/api/v1/member/makerspaces/{space.pk}/payments/{payment.pk}/checkout")


def _return_url(monkeypatch):
    monkeypatch.setattr(
        "apps.payments.services_checkout.member_payment_return_url",
        lambda _space: "https://space.example/member",
    )


def test_a_cash_only_debt_is_not_claimed_by_a_checkout_that_cannot_run():
    space, member, payment = _unclaimed_debt("claim-cash-only")

    response = _checkout(space, member, payment)

    assert response.status_code == 503
    assert response.data["code"] == "payments_unavailable"
    payment.refresh_from_db()
    assert payment.provider == Payment.Provider.UNCLAIMED
    assert payment.online_rail is None


def test_the_first_stripe_checkout_claims_the_debt(monkeypatch):
    space, member, payment = _unclaimed_debt("claim-stripe")
    configured_settings(space)
    _return_url(monkeypatch)
    monkeypatch.setattr(
        "apps.payments.services_checkout.stripe_client.create_checkout_session",
        lambda *_a, **_k: {"id": "cs_claim", "url": "https://checkout.stripe.test/cs_claim"},
    )

    response = _checkout(space, member, payment)

    assert response.status_code == 200, response.data
    payment.refresh_from_db()
    assert payment.provider == Payment.Provider.STRIPE
    assert payment.stripe_provider == Payment.StripeProvider.RAW
    assert payment.online_rail == Payment.OnlineRail.CHECKOUT
    assert payment.stripe_checkout_session_id == "cs_claim"


def test_the_first_razorpay_checkout_claims_the_debt_through_the_seam(monkeypatch):
    space, member, payment = _unclaimed_debt("claim-razorpay")
    configure_razorpay(space)
    _return_url(monkeypatch)
    sent = []
    monkeypatch.setattr(
        RazorpayProvider,
        "_request",
        lambda _self, _source, method, path, body=None: sent.append((method, path, body))
        or {"id": "plink_claim", "short_url": "https://rzp.io/i/claim"},
    )

    response = _checkout(space, member, payment)

    assert response.status_code == 200, response.data
    assert response.data["checkout_url"] == "https://rzp.io/i/claim"
    assert sent[0][1] == "/payment_links" and sent[0][2]["amount"] == 2000
    payment.refresh_from_db()
    assert payment.provider == Payment.Provider.RAZORPAY
    assert payment.external_order_id == "plink_claim"


def test_the_database_permits_one_claim_and_never_a_second(monkeypatch):
    _space, _member, payment = _unclaimed_debt("claim-trigger")

    assert Payment.objects.filter(pk=payment.pk).update(provider=Payment.Provider.STRIPE) == 1
    for target in (Payment.Provider.RAZORPAY, Payment.Provider.UNCLAIMED):
        with pytest.raises(DatabaseError), transaction.atomic():
            Payment.objects.filter(pk=payment.pk).update(provider=target)
    payment.refresh_from_db()
    assert payment.provider == Payment.Provider.STRIPE


def test_the_model_refuses_to_move_a_claimed_row():
    _space, _member, payment = _unclaimed_debt("claim-model")
    payment.provider = Payment.Provider.STRIPE
    payment.save(update_fields=["provider", "updated_at"])

    payment.provider = Payment.Provider.RAZORPAY
    with pytest.raises(ValidationError, match="provenance is immutable"):
        payment.save()
