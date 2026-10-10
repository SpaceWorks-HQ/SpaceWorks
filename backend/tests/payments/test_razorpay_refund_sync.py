"""A Razorpay refund through the provider seam: the synchronous answer settles or holds it."""

from decimal import Decimal

import pytest

from apps.payments.models import Payment, Refund
from apps.payments.providers.razorpay import RazorpayProvider
from tests.payments.test_razorpay_provider import configure_razorpay
from tests.return_helpers import (
    authenticated_client,
    make_accepted_request,
    make_member,
    make_product,
    make_space,
)

pytestmark = pytest.mark.django_db


def _paid_razorpay_deposit(slug):
    space = make_space(slug)
    staff = make_member(f"{slug}-staff", space)
    configure_razorpay(space)
    request = make_accepted_request(space, make_product(space), 1)
    payment = Payment.objects.create(
        makerspace=space, subject_type=Payment.SubjectType.LOAN_DEPOSIT,
        subject_id=request.pk, member=request.requester, amount=Decimal("500.00"),
        currency="inr", created_by=staff, provider=Payment.Provider.RAZORPAY,
    )
    Payment.objects.filter(pk=payment.pk).update(
        status=Payment.Status.PAID_ONLINE, external_payment_id="pay_rzp_1"
    )
    return space, staff, payment


@pytest.mark.parametrize(
    ("provider_status", "expected"),
    [("processed", Refund.Status.SUCCEEDED), ("pending", Refund.Status.PENDING)],
)
def test_a_razorpay_refund_is_sent_in_paise_and_settled_from_its_answer(
    monkeypatch, provider_status, expected
):
    space, staff, payment = _paid_razorpay_deposit(f"rzp-refund-{provider_status}")
    sent = []
    monkeypatch.setattr(
        RazorpayProvider,
        "_request",
        lambda _self, _source, method, path, body=None: sent.append((method, path, body))
        or {"id": f"rfnd_{provider_status}", "status": provider_status},
    )

    response = authenticated_client(staff).post(
        f"/api/v1/admin/makerspace/{space.pk}/payments/{payment.pk}/refund",
        {"amount": "120.50", "reason": "partial return"}, format="json",
    )

    assert response.status_code == 200, response.data
    method, path, body = sent[0]
    assert (method, path) == ("POST", "/payments/pay_rzp_1/refund")
    assert body["amount"] == 12050
    refund = Refund.objects.get(payment=payment)
    assert (refund.status, refund.external_refund_id) == (expected, f"rfnd_{provider_status}")
    payment.refresh_from_db()
    assert payment.status == Payment.Status.PAID_ONLINE
