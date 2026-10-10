"""Admission activation follows committed money without reversing settlement."""

import pytest
from django.core.exceptions import ValidationError
from django.db import transaction

from apps.accounts import rbac
from apps.makerspaces.models import MembershipRequest
from apps.payments import admission_settlement
from apps.payments.models import ManualSettlement, Payment
from apps.payments.providers.base import WebhookEvent
from apps.payments.reconciliation import reconcile_payments
from apps.payments.services_webhooks import apply_razorpay_webhook_event, apply_webhook_event
from apps.payments.subjects import resolve_subject_labels, subject_label
from tests.payments.test_reconciliation import custom_actor
from tests.return_helpers import make_member, make_space, make_user, settlement_details

pytestmark = pytest.mark.django_db


def admission_charge(*, provider=Payment.Provider.UNCLAIMED):
    space = make_space("admission-settlement")
    manager = make_member("admission-settlement-manager", space)
    applicant = make_user("admission-settlement-applicant", access_status="active")
    request = MembershipRequest.objects.create(
        makerspace=space, user=applicant, requested_by=applicant,
        kind="request", state="requested",
    )
    payment = Payment.objects.create(
        makerspace=space, subject_type=Payment.SubjectType.MEMBERSHIP_REQUEST,
        subject_id=request.pk, member=applicant, amount="12.00", currency="usd",
        created_by=manager, provider=provider,
    )
    return space, manager, request, payment


@pytest.mark.parametrize("status", [Payment.Status.PAID_OFFLINE, Payment.Status.WAIVED])
def test_offline_or_waive_resumes_only_after_commit(
    status, monkeypatch, django_capture_on_commit_callbacks,
):
    space, manager, request, payment = admission_charge()
    calls = []
    monkeypatch.setattr(
        "apps.makerspaces.membership_admission_payments.resume_after_payment", calls.append,
    )
    with django_capture_on_commit_callbacks(execute=True):
        reconcile_payments(
            actor=manager, makerspace_id=space.pk, payment_ids=[payment.pk],
            target_status=status,
            settlement=settlement_details(reference="desk-42") if status == "paid_offline" else None,
        )
        assert calls == []
        payment.refresh_from_db()
        assert payment.status == status
        assert ManualSettlement.objects.filter(payment=payment).exists() == (status == "paid_offline")
    assert calls == [payment.pk]


@pytest.mark.parametrize("kind", ["hosted", "async", "native", "razorpay"])
def test_all_gateway_settlements_schedule_admission_resume(
    kind, monkeypatch, django_capture_on_commit_callbacks,
):
    provider = Payment.Provider.RAZORPAY if kind == "razorpay" else Payment.Provider.STRIPE
    space, manager, request, payment = admission_charge(provider=provider)
    calls = []
    monkeypatch.setattr(
        "apps.makerspaces.membership_admission_payments.resume_after_payment", calls.append,
    )
    if kind == "razorpay":
        Payment.objects.filter(pk=payment.pk).update(external_order_id="order_admission")
        event = WebhookEvent(event_id="evt_admission", is_paid=True,
                             order_id="order_admission", payment_id="pay_admission")
        apply = lambda: apply_razorpay_webhook_event(space, event)
    else:
        Payment.objects.filter(pk=payment.pk).update(
            stripe_checkout_session_id="cs_admission", stripe_payment_intent_id="pi_admission",
        )
        event_type = {"hosted": "checkout.session.completed",
                      "async": "checkout.session.async_payment_succeeded",
                      "native": "payment_intent.succeeded"}[kind]
        event = {"id": "evt_admission", "type": event_type,
                 "data": {"object": {"id": "pi_admission" if kind == "native" else "cs_admission",
                                     "payment_status": "paid"}}}
        apply = lambda: apply_webhook_event(space, event)
    with django_capture_on_commit_callbacks(execute=True):
        assert apply().status == Payment.Status.PAID_ONLINE
        assert calls == []
        assert apply() is None
    assert calls == [payment.pk]


def test_activation_failure_keeps_committed_receipt_and_logs_no_personal_data(
    monkeypatch, django_capture_on_commit_callbacks, caplog,
):
    space, manager, request, payment = admission_charge()

    def refuse(_payment_id):
        raise ValueError("personal-contact@example.test")

    monkeypatch.setattr(
        "apps.makerspaces.membership_admission_payments.resume_after_payment", refuse,
    )
    with django_capture_on_commit_callbacks(execute=True):
        reconcile_payments(
            actor=manager, makerspace_id=space.pk, payment_ids=[payment.pk],
            target_status=Payment.Status.PAID_OFFLINE, settlement=settlement_details(),
        )
    payment.refresh_from_db()
    assert payment.status == Payment.Status.PAID_OFFLINE
    assert ManualSettlement.objects.filter(payment=payment).count() == 1
    assert "membership_admission_resume_failed" in caplog.text
    assert "personal-contact" not in caplog.text


@pytest.mark.parametrize("provider", [Payment.Provider.STRIPE, Payment.Provider.RAZORPAY])
def test_money_received_after_waiver_also_resumes_admission(
    provider, monkeypatch, django_capture_on_commit_callbacks,
):
    space, manager, request, payment = admission_charge(provider=provider)
    Payment.objects.filter(pk=payment.pk).update(
        stripe_checkout_session_id="cs_late_admission" if provider == "stripe" else None,
        external_order_id="order_late_admission" if provider == "razorpay" else None,
        status=Payment.Status.WAIVED,
    )
    calls = []
    monkeypatch.setattr(
        "apps.makerspaces.membership_admission_payments.resume_after_payment", calls.append,
    )
    with django_capture_on_commit_callbacks(execute=True):
        if provider == "stripe":
            result = apply_webhook_event(space, {
                "id": "evt_late_admission", "type": "checkout.session.completed",
                "data": {"object": {"id": "cs_late_admission", "payment_status": "paid"}},
            })
        else:
            result = apply_razorpay_webhook_event(space, WebhookEvent(
                event_id="evt_late_admission", is_paid=True,
                order_id="order_late_admission", payment_id="pay_late_admission",
            ))
        assert result.status == Payment.Status.PAID_ONLINE
        assert calls == []
    assert calls == [payment.pk]


def test_rolled_back_settlement_does_not_resume(monkeypatch, django_capture_on_commit_callbacks):
    space, manager, request, payment = admission_charge()
    calls = []
    monkeypatch.setattr(
        "apps.makerspaces.membership_admission_payments.resume_after_payment", calls.append,
    )
    with django_capture_on_commit_callbacks(execute=True):
        with pytest.raises(ValueError):
            with transaction.atomic():
                reconcile_payments(
                    actor=manager, makerspace_id=space.pk, payment_ids=[payment.pk],
                    target_status=Payment.Status.WAIVED,
                )
                raise ValueError("rollback")
    assert calls == []
    payment.refresh_from_db()
    assert payment.status == Payment.Status.PENDING


def test_membership_coordinator_can_reconcile_only_their_space():
    space, manager, request, payment = admission_charge()
    actor = custom_actor("admission-coordinator", space, [rbac.Action.MANAGE_MEMBERS])
    reconcile_payments(actor=actor, makerspace_id=space.pk, payment_ids=[payment.pk],
                       target_status=Payment.Status.WAIVED)
    from rest_framework.exceptions import PermissionDenied
    other = make_space("admission-other")
    outsider = custom_actor("admission-other-coordinator", other, [rbac.Action.MANAGE_MEMBERS])
    # Authority can still be checked on the terminal row without changing money.
    from apps.payments.reconciliation_authority import _require_subject_authority
    with pytest.raises(PermissionDenied):
        _require_subject_authority(outsider, [payment])


def test_admission_payment_requires_same_tenant_and_applicant():
    space, manager, request, payment = admission_charge()
    other = make_space("admission-validation-other")
    with pytest.raises(ValidationError):
        Payment.objects.create(makerspace=other, subject_type="membership_request",
                               subject_id=request.pk, member=request.user,
                               amount="5", currency="usd", created_by=manager)
    payment.member = manager
    with pytest.raises(ValidationError):
        payment.full_clean()
    assert subject_label(payment, resolve_subject_labels([payment])) == "Membership admission"


def test_canceled_admission_charge_never_schedules_activation(monkeypatch):
    space, manager, request, payment = admission_charge()
    payment.status = Payment.Status.CANCELED
    callbacks = []
    monkeypatch.setattr(admission_settlement.transaction, "on_commit", callbacks.append)
    admission_settlement.resume_admission_after_settlement(payment)
    assert callbacks == []
