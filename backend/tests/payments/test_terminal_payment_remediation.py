import pytest

from apps.audit.models import AuditLog
from apps.payments.models import Payment, ProcessedStripeEvent
from apps.payments.services import apply_webhook_event
from tests.payments.test_models import configured_settings
from tests.payments.test_reconciliation import action_url, payment
from tests.return_helpers import authenticated_client, make_member, make_space


pytestmark = pytest.mark.django_db


def native_payment(name):
    space = make_space(name)
    manager = make_member(f"{name}-manager", space)
    configured_settings(space)
    row = payment(space, manager, Payment.SubjectType.BOOKING, 1)
    Payment.objects.filter(pk=row.pk).update(
        online_rail=Payment.OnlineRail.NATIVE_PAYMENT_INTENT,
        stripe_payment_intent_id=f"pi_{name}",
    )
    row.refresh_from_db()
    return space, manager, row


@pytest.mark.parametrize(
    ("action", "expected_status"),
    [
        ("waive", Payment.Status.WAIVED),
        ("mark-offline", Payment.Status.PAID_OFFLINE),
    ],
)
def test_reconciliation_cancels_a_live_native_payment_intent(
    monkeypatch, action, expected_status
):
    space, manager, row = native_payment(f"native-cancel-{action}")
    canceled = []

    def cancel(source, intent_id):
        canceled.append((source, intent_id))
        return True

    monkeypatch.setattr(
        "apps.payments.reconciliation.stripe_client.cancel_payment_intent", cancel
    )

    response = authenticated_client(manager).post(action_url(space, row, action))

    assert response.status_code == 200
    row.refresh_from_db()
    assert row.status == expected_status
    assert canceled[0][0].provider == Payment.StripeProvider.RAW
    assert canceled[0][1] == row.stripe_payment_intent_id


def test_native_intent_cancellation_failure_does_not_block_reconciliation(monkeypatch):
    space, manager, row = native_payment("native-cancel-failure")
    monkeypatch.setattr(
        "apps.payments.reconciliation.stripe_client.cancel_payment_intent",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("Stripe down")),
    )

    response = authenticated_client(manager).post(action_url(space, row, "waive"))

    assert response.status_code == 200
    row.refresh_from_db()
    assert row.status == Payment.Status.WAIVED
    assert AuditLog.objects.filter(
        action="payment.waived", target_id=str(row.pk)
    ).count() == 1


def paid_event(row, event_id):
    return {
        "id": event_id,
        "type": "payment_intent.succeeded",
        "data": {"object": {"id": row.stripe_payment_intent_id}},
    }


def test_paid_webhook_after_waiver_promotes_payment_to_paid_online():
    space, _manager, row = native_payment("paid-after-waived")
    Payment.objects.filter(pk=row.pk).update(status=Payment.Status.WAIVED)

    result = apply_webhook_event(space, paid_event(row, "evt_paid_after_waived"))

    result.refresh_from_db()
    assert result.status == Payment.Status.PAID_ONLINE
    anomaly = AuditLog.objects.get(
        action="payment.paid_after_terminal", target_id=str(row.pk)
    )
    assert anomaly.meta["prior_status"] == Payment.Status.WAIVED
    assert anomaly.meta["resolved_status"] == Payment.Status.PAID_ONLINE


def test_paid_webhook_after_offline_payment_requires_a_refund():
    space, _manager, row = native_payment("paid-after-offline")
    Payment.objects.filter(pk=row.pk).update(status=Payment.Status.PAID_OFFLINE)

    result = apply_webhook_event(space, paid_event(row, "evt_paid_after_offline"))

    result.refresh_from_db()
    assert result.status == Payment.Status.PAID_OFFLINE
    refund = AuditLog.objects.get(
        action="payment.double_paid_refund_required", target_id=str(row.pk)
    )
    assert refund.meta == {
        "stripe_event_id": "evt_paid_after_offline",
        "prior_status": Payment.Status.PAID_OFFLINE,
    }


def test_replayed_terminal_payment_webhook_has_no_second_effect():
    space, _manager, row = native_payment("terminal-replay")
    Payment.objects.filter(pk=row.pk).update(status=Payment.Status.WAIVED)
    event = paid_event(row, "evt_terminal_replay")

    first = apply_webhook_event(space, event)
    audit_count = AuditLog.objects.filter(target_id=str(row.pk)).count()
    second = apply_webhook_event(space, event)

    first.refresh_from_db()
    assert first.status == Payment.Status.PAID_ONLINE
    assert second is None
    assert AuditLog.objects.filter(target_id=str(row.pk)).count() == audit_count
    assert ProcessedStripeEvent.objects.filter(
        makerspace=space, stripe_event_id=event["id"]
    ).count() == 1
