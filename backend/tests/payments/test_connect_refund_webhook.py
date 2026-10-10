"""A refund on a Connect-routed charge settles from the PLATFORM webhook, scoped by account."""

from decimal import Decimal

import pytest

from apps.payments.models import Payment, Refund
from apps.payments.services import apply_connect_webhook_event
from tests.payments.test_refunds import paid_deposit, stripe_space

pytestmark = pytest.mark.django_db


def _event(event_id, account):
    return {
        "id": event_id,
        "account": account,
        "type": "refund.updated",
        "data": {"object": {"id": "re_connect", "payment_intent": "pi_connect", "status": "succeeded", "amount": 300}},
    }


def test_a_connect_refund_settles_once_and_only_for_its_own_account(monkeypatch):
    makerspace, staff = stripe_space("connect-refund-webhook", monkeypatch, [])
    payment = paid_deposit(makerspace, staff)
    Payment.objects.filter(pk=payment.pk).update(
        stripe_provider=Payment.StripeProvider.CONNECT,
        stripe_connected_account_id="acct_refunds",
        stripe_payment_intent_id="pi_connect",
    )
    refund = Refund.objects.create(
        payment=payment, amount=Decimal("3.00"), currency="usd",
        provider=Payment.Provider.STRIPE, created_by=staff,
    )

    assert apply_connect_webhook_event(_event("evt_other_account", "acct_someone_else")) is None
    refund.refresh_from_db()
    assert refund.status == Refund.Status.PENDING

    settled = apply_connect_webhook_event(_event("evt_connect_refund", "acct_refunds"))
    assert [row.status for row in settled] == [Refund.Status.SUCCEEDED]
    assert apply_connect_webhook_event(_event("evt_connect_refund", "acct_refunds")) is None
    refund.refresh_from_db()
    assert (refund.status, refund.external_refund_id) == (Refund.Status.SUCCEEDED, "re_connect")
