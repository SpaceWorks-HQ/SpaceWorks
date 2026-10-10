"""The native PaymentSheet is Stripe-only, and must say so before calling anyone.

A Razorpay source carries the Razorpay key secret in `secret_key`. `create_mobile_intent`
never checked the vendor, so on a Razorpay space it called Stripe with that secret as the
API key -- a credential handed to the wrong third party -- and then failed as a 503 anyway.
"""

from decimal import Decimal

import pytest

from apps.payments import stripe_client
from apps.payments.models import Payment
from apps.payments.services import create_payment
from apps.payments.services_mobile import create_mobile_intent
from tests.payments.test_machine_payments import service_request
from tests.payments.test_mobile_payments import device_client
from tests.payments.test_razorpay_provider import configure_razorpay
from tests.return_helpers import enable_online_rail, make_member, make_space

pytestmark = pytest.mark.django_db


def _razorpay_debt(slug, *, claimed):
    space = make_space(slug)
    enable_online_rail(space, "machines")
    member = make_member(f"{slug}-member", space)
    subject = service_request(space, member)
    if claimed:
        configure_razorpay(space)
    payment = create_payment(
        makerspace=space,
        subject_type=Payment.SubjectType.MACHINE_SERVICE_REQUEST,
        subject_id=subject.pk,
        member=member,
        amount=Decimal("12.50"),
        currency="inr",
        created_by=member,
    )
    if not claimed:
        configure_razorpay(space)
    return space, member, payment


def _stripe_must_not_be_called(monkeypatch):
    calls = []
    for name in ("create_payment_intent", "retrieve_payment_intent"):
        monkeypatch.setattr(
            stripe_client, name, lambda *args, _name=name, **kwargs: calls.append(_name)
        )
    return calls


@pytest.mark.parametrize("claimed", [True, False])
def test_a_razorpay_space_is_refused_without_calling_stripe(monkeypatch, claimed):
    space, member, payment = _razorpay_debt(f"mobile-vendor-{claimed}", claimed=claimed)
    calls = _stripe_must_not_be_called(monkeypatch)
    before = Payment.objects.get(pk=payment.pk).provider

    with pytest.raises(stripe_client.PaymentsUnavailable):
        create_mobile_intent(payment.pk, actor=member)

    assert calls == []
    payment.refresh_from_db()
    # An unclaimed debt is not claimed by a refusal: the claim rolls back with it.
    assert payment.provider == before
    assert payment.online_rail is None
    assert payment.stripe_payment_intent_id is None


def test_the_native_endpoint_answers_a_sanitized_503_for_a_razorpay_space(monkeypatch):
    space, member, payment = _razorpay_debt("mobile-vendor-http", claimed=True)
    calls = _stripe_must_not_be_called(monkeypatch)

    response = device_client(member, space).post(
        f"/api/v1/member/makerspaces/{space.pk}/payments/{payment.pk}/mobile-intent",
        format="json",
    )

    assert response.status_code == 503
    assert response.data["code"] == "payments_unavailable"
    assert calls == []
