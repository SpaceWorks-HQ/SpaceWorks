"""Refunds: a separate ledger line on an immutable, online-paid Payment."""

import hashlib
import hmac
import json
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse

from apps.audit.models import AuditLog
from apps.payments import stripe_client
from apps.payments.models import MakerspacePaymentSettings, Payment, ProcessedStripeEvent, Refund
from apps.payments.services import apply_webhook_event
from tests.payments.test_models import configured_settings
from tests.return_helpers import (
    authenticated_client,
    make_accepted_request,
    make_member,
    make_product,
    make_space,
    make_user,
)

pytestmark = pytest.mark.django_db


class FakeStripe:
    """`v1.refunds.create` double. `responses` are popped in order; an Exception is raised."""

    calls = []
    responses = []

    class StripeClient:
        def __init__(self, *, api_key):
            outer = FakeStripe

            class Refunds:
                def create(self, *, params, options):
                    outer.calls.append((params, options))
                    response = outer.responses.pop(0)
                    if isinstance(response, Exception):
                        raise response
                    return response

            self.v1 = type("V1", (), {"refunds": Refunds()})()


def stripe_space(slug, monkeypatch, responses):
    makerspace = make_space(slug)
    staff = make_member(f"{slug}-staff", makerspace)
    configured_settings(makerspace)
    FakeStripe.calls, FakeStripe.responses = [], list(responses)
    monkeypatch.setattr(stripe_client, "_stripe_module", lambda: FakeStripe)
    return makerspace, staff


def paid_deposit(makerspace, staff, *, status=Payment.Status.PAID_ONLINE, amount="10.00"):
    request = make_accepted_request(makerspace, make_product(makerspace), 1)
    payment = Payment.objects.create(
        makerspace=makerspace,
        subject_type=Payment.SubjectType.LOAN_DEPOSIT,
        subject_id=request.pk,
        member=request.requester,
        amount=Decimal(amount),
        currency="usd",
        created_by=staff,
        subject_label="Loan deposit",
    )
    Payment.objects.filter(pk=payment.pk).update(status=status, stripe_payment_intent_id="pi_1")
    payment.refresh_from_db()
    return payment


def refund_url(payment):
    return reverse("payment-reconciliation-refund", args=[payment.makerspace_id, payment.pk])


def test_only_online_paid_payments_can_be_refunded(monkeypatch):
    makerspace, staff = stripe_space("refund-offline", monkeypatch, [])
    payment = paid_deposit(makerspace, staff, status=Payment.Status.PAID_OFFLINE)

    response = authenticated_client(staff).post(
        refund_url(payment), {"amount": "5.00", "reason": "cash back"}, format="json"
    )

    assert response.status_code == 400
    assert response.data["code"] == "refund_not_online"
    assert not Refund.objects.exists()
    assert FakeStripe.calls == []


def test_partial_refunds_sum_and_over_refund_is_refused(monkeypatch):
    makerspace, staff = stripe_space(
        "refund-partial", monkeypatch,
        [{"id": "re_1", "status": "succeeded"}, {"id": "re_2", "status": "succeeded"}],
    )
    payment = paid_deposit(makerspace, staff)
    client = authenticated_client(staff)

    first = client.post(refund_url(payment), {"amount": "4.00", "reason": "Returned early"}, format="json")
    assert first.status_code == 200
    assert Decimal(first.data["refunded_amount"]) == Decimal("4.00")
    assert [row["status"] for row in first.data["refunds"]] == ["succeeded"]
    params, options = FakeStripe.calls[0]
    assert params["payment_intent"] == "pi_1" and params["amount"] == 400
    assert options["idempotency_key"].startswith("payment-refund-")

    second = client.post(refund_url(payment), {"amount": "6.00"}, format="json")
    assert second.status_code == 200
    assert Decimal(second.data["refunded_amount"]) == Decimal("10.00")

    third = client.post(refund_url(payment), {"amount": "0.01"}, format="json")
    assert third.status_code == 400
    assert third.data["code"] == "refund_exceeds_balance"
    assert Refund.objects.filter(payment=payment).count() == 2
    payment.refresh_from_db()
    assert payment.status == Payment.Status.PAID_ONLINE  # the Payment row never moved

    entry = AuditLog.objects.filter(action="payment.refunded").order_by("pk").first()
    refund = Refund.objects.filter(payment=payment).order_by("pk").first()
    assert entry.meta == {"payment_id": payment.pk, "refund_id": refund.pk, "amount": "4.00"}


def test_pending_refund_holds_the_balance_and_the_webhook_settles_it_once(monkeypatch):
    makerspace, staff = stripe_space(
        "refund-pending", monkeypatch, [{"id": "re_1", "status": "pending"}]
    )
    payment = paid_deposit(makerspace, staff)
    client = authenticated_client(staff)

    response = client.post(refund_url(payment), {"amount": "4.00"}, format="json")
    assert response.status_code == 200
    assert Decimal(response.data["refunded_amount"]) == Decimal("0.00")
    refund = Refund.objects.get(payment=payment)
    assert (refund.status, refund.external_refund_id) == (Refund.Status.PENDING, "re_1")
    assert AuditLog.objects.filter(action="payment.refund_requested").count() == 1

    over = client.post(refund_url(payment), {"amount": "6.01"}, format="json")
    assert over.status_code == 400  # pending money is not refundable twice

    event = {
        "id": "evt_refund_1",
        "type": "refund.updated",
        "data": {"object": {"id": "re_1", "payment_intent": "pi_1", "status": "succeeded", "amount": 400}},
    }
    settled = apply_webhook_event(makerspace, event)
    assert [row.status for row in settled] == [Refund.Status.SUCCEEDED]
    assert apply_webhook_event(makerspace, event) is None
    refund.refresh_from_db()
    assert refund.status == Refund.Status.SUCCEEDED and refund.settled_at is not None
    assert ProcessedStripeEvent.objects.filter(makerspace=makerspace).count() == 1
    assert AuditLog.objects.filter(action="payment.refunded").count() == 1


def test_charge_refunded_binds_an_unbound_pending_refund_by_amount(monkeypatch):
    makerspace, staff = stripe_space("refund-charge-event", monkeypatch, [])
    payment = paid_deposit(makerspace, staff)
    refund = Refund.objects.create(
        payment=payment, amount=Decimal("3.00"), currency="usd",
        provider=Payment.Provider.STRIPE, created_by=staff,
    )

    apply_webhook_event(
        makerspace,
        {
            "id": "evt_charge_1",
            "type": "charge.refunded",
            "data": {"object": {
                "id": "ch_1",
                "payment_intent": "pi_1",
                "refunds": {"data": [{"id": "re_dash", "status": "succeeded", "amount": 300}]},
            }},
        },
    )

    refund.refresh_from_db()
    assert (refund.status, refund.external_refund_id) == (Refund.Status.SUCCEEDED, "re_dash")


def test_provider_failure_marks_the_refund_failed_and_frees_the_balance(monkeypatch):
    makerspace, staff = stripe_space(
        "refund-failure", monkeypatch,
        [RuntimeError("stripe down"), {"id": "re_ok", "status": "succeeded"}],
    )
    payment = paid_deposit(makerspace, staff)
    client = authenticated_client(staff)

    failed = client.post(refund_url(payment), {"amount": "10.00"}, format="json")
    assert failed.status_code == 502
    assert failed.data["code"] == "refund_provider_failed"
    refund = Refund.objects.get(payment=payment)
    assert refund.status == Refund.Status.FAILED
    assert AuditLog.objects.filter(action="payment.refund_failed").count() == 1

    retry = client.post(refund_url(payment), {"amount": "10.00"}, format="json")
    assert retry.status_code == 200
    assert Decimal(retry.data["refunded_amount"]) == Decimal("10.00")


def test_refund_needs_the_subject_authority_and_the_right_makerspace(monkeypatch):
    makerspace, staff = stripe_space("refund-authz", monkeypatch, [{"id": "re_1", "status": "succeeded"}])
    payment = paid_deposit(makerspace, staff)
    outsider = make_user("refund-outsider")

    assert authenticated_client(outsider).post(refund_url(payment), {"amount": "1.00"}, format="json").status_code == 403
    other = make_space("refund-other-space")
    wrong_space = reverse("payment-reconciliation-refund", args=[other.pk, payment.pk])
    assert authenticated_client(staff).post(wrong_space, {"amount": "1.00"}, format="json").status_code == 404
    assert not Refund.objects.exists()


def test_settled_refunds_are_immutable():
    makerspace = make_space("refund-immutable")
    staff = make_member("refund-immutable-staff", makerspace)
    payment = paid_deposit(makerspace, staff)
    refund = Refund.objects.create(
        payment=payment, amount=Decimal("1.00"), currency="usd",
        provider=Payment.Provider.STRIPE, created_by=staff, status=Refund.Status.SUCCEEDED,
    )

    refund.status = Refund.Status.FAILED
    with pytest.raises(ValidationError):
        refund.save()
    with pytest.raises(ValidationError):
        Refund(
            payment=payment, amount=Decimal("9.50"), currency="usd",
            provider=Payment.Provider.STRIPE, created_by=staff,
        ).save()


def test_razorpay_refund_processed_settles_a_pending_refund_idempotently(client):
    makerspace = make_space("refund-razorpay")
    staff = make_member("refund-razorpay-staff", makerspace)
    row = MakerspacePaymentSettings(makerspace=makerspace, provider="razorpay")
    row.razorpay_key_id = "rzp_test_key"
    row.set_razorpay_key_secret("rzp_test_secret")
    row.set_razorpay_webhook_secret("rzp_whsec")
    row.save()
    request = make_accepted_request(makerspace, make_product(makerspace), 1)
    payment = Payment.objects.create(
        makerspace=makerspace, subject_type=Payment.SubjectType.LOAN_DEPOSIT,
        subject_id=request.pk, member=request.requester, amount=Decimal("10.00"),
        currency="inr", created_by=staff, provider=Payment.Provider.RAZORPAY,
        external_payment_id="pay_1",
    )
    Payment.objects.filter(pk=payment.pk).update(status=Payment.Status.PAID_ONLINE)
    refund = Refund.objects.create(
        payment=payment, amount=Decimal("4.00"), currency="inr",
        provider=Payment.Provider.RAZORPAY, created_by=staff, external_refund_id="rfnd_1",
    )
    body = json.dumps({
        "event": "refund.processed",
        "payload": {"refund": {"entity": {
            "id": "rfnd_1", "payment_id": "pay_1", "amount": 400, "status": "processed",
        }}},
    }).encode()
    signature = hmac.new(b"rzp_whsec", body, hashlib.sha256).hexdigest()
    post = lambda: client.post(  # noqa: E731
        reverse("razorpay-webhook", args=[makerspace.public_code]),
        data=body, content_type="application/json",
        HTTP_X_RAZORPAY_SIGNATURE=signature, HTTP_X_RAZORPAY_EVENT_ID="evt_rf_1",
    )

    assert post().status_code == 200
    assert post().status_code == 200

    refund.refresh_from_db()
    assert refund.status == Refund.Status.SUCCEEDED
    assert ProcessedStripeEvent.objects.filter(makerspace=makerspace).count() == 1
    assert AuditLog.objects.filter(action="payment.refunded").count() == 1
