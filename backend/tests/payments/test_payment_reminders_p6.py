"""F1 payment consumer: durable claims, local days and owner-only disclosure."""

from datetime import datetime, timedelta, timezone as utc
from types import SimpleNamespace

import pytest
from django.utils import timezone

from apps.integrations import notify
from apps.integrations.models import EmailLog, NotificationPreference
from apps.operations.models_reminders import ReminderSchedule
from apps.operations.reminder_services import schedule_reminders
from apps.operations.reminder_sweeper import run_reminder_sweep
from apps.payments.models import MakerspaceBillingSettings
from apps.payments.reminders import _steps
from apps.payments.services_refunds_offline import amend_offline_refund, record_offline_refund
from tests.module_helpers import disable_module
from tests.payments.test_billing_due_p5 import new_charge
from tests.payments.test_offline_refunds import cash_deposit, payload
from tests.return_helpers import make_member, make_space

pytestmark = pytest.mark.django_db(transaction=True)


def reminder_space(slug):
    space = make_space(slug)
    space.enabled_modules = sorted(set(space.enabled_modules) | {"notifications", "email"})
    space.enabled_features = sorted(set(space.enabled_features) | {"billing.reminders"})
    space.save(update_fields=["enabled_modules", "enabled_features"])
    disable_module(space, "payments")
    staff = make_member(f"{slug}-staff", space)
    NotificationPreference.objects.create(makerspace=space, feature="payments", channel="email", enabled=True)
    return space, staff


@pytest.fixture
def deliveries(monkeypatch):
    emails, channels = [], []
    monkeypatch.setattr(notify, "dispatch_email", lambda **data: emails.append(data) or SimpleNamespace(status=EmailLog.Status.SENT))
    monkeypatch.setattr(notify, "dispatch_channel", lambda **data: channels.append(data) or [])
    return emails, channels


def test_due_today_and_overdue_ladder_dispatch_once_only_to_owner(deliveries):
    space, staff = reminder_space("p6-once")
    MakerspaceBillingSettings.objects.create(makerspace=space, reminder_days_after=[3, 7], max_reminders=4)
    now = datetime(2026, 10, 10, 12, tzinfo=utc.utc)
    payment = new_charge(space, staff, due_at=now)
    # Creation is a separate edge; inspect only sweeper dispatches.
    emails, channels = deliveries
    emails.clear()
    assert run_reminder_sweep(now=now)["dispatched"] == 1
    assert run_reminder_sweep(now=now)["dispatched"] == 0
    assert [row["to_email"] for row in emails] == [staff.email]
    assert all(row["audience"] == "requester" for row in emails)
    assert channels == []
    emails.clear()
    assert run_reminder_sweep(now=now + timedelta(days=3))["dispatched"] == 1
    assert run_reminder_sweep(now=now + timedelta(days=3))["dispatched"] == 0
    assert "payment_overdue" in emails[0]["text_body"]
    payment.refresh_from_db()
    assert payment.status == "pending"


def test_due_soon_then_today_are_distinct_idempotent_steps(deliveries):
    space, staff = reminder_space("p6-before")
    now = datetime(2026, 10, 10, 12, tzinfo=utc.utc)
    new_charge(space, staff, due_at=now + timedelta(days=3))
    emails, _ = deliveries
    emails.clear()
    assert run_reminder_sweep(now=now)["dispatched"] == 1
    assert "payment_due_soon" in emails[0]["text_body"]
    assert run_reminder_sweep(now=now + timedelta(days=3))["dispatched"] == 1
    assert "payment_due_today" in emails[-1]["text_body"]


def test_downtime_expires_due_today_and_sends_only_latest_overdue_step(deliveries):
    space, staff = reminder_space("p6-downtime")
    MakerspaceBillingSettings.objects.create(makerspace=space, reminder_days_after=[3, 7], max_reminders=4)
    due = datetime(2026, 10, 10, 12, tzinfo=utc.utc)
    new_charge(space, staff, due_at=due)
    emails, channels = deliveries
    emails.clear()
    assert run_reminder_sweep(now=due + timedelta(days=2))["dispatched"] == 0
    assert not emails
    assert run_reminder_sweep(now=due + timedelta(days=10))["dispatched"] == 1
    assert len(emails) == 1 and "payment_overdue" in emails[0]["text_body"]
    assert "payment_due_today" not in emails[0]["text_body"]
    assert run_reminder_sweep(now=due + timedelta(days=10))["dispatched"] == 0
    assert not channels


@pytest.mark.parametrize("gate", ["notifications", "email", "feature", "matrix"])
def test_disabled_reminders_do_not_claim_or_send(gate, deliveries):
    space, staff = reminder_space(f"p6-gate-{gate}")
    now = timezone.now()
    new_charge(space, staff, due_at=now)
    emails, _ = deliveries
    emails.clear()
    if gate in {"notifications", "email"}:
        disable_module(space, gate)
    elif gate == "feature":
        space.enabled_features = [key for key in space.enabled_features if key != "billing.reminders"]
        space.save(update_fields=["enabled_features"])
    else:
        NotificationPreference.objects.filter(makerspace=space, feature="payments", channel="email").update(enabled=False)
    assert run_reminder_sweep(now=now)["dispatched"] == 0
    assert not ReminderSchedule.objects.filter(makerspace=space).exists()
    assert not emails


def test_default_off_and_maximum_zero_prevent_automatic_mail(deliveries):
    space = make_space("p6-default-off")
    staff = make_member("p6-default-staff", space)
    now = timezone.now()
    new_charge(space, staff, due_at=now)
    assert run_reminder_sweep(now=now)["dispatched"] == 0
    space, staff = reminder_space("p6-zero")
    MakerspaceBillingSettings.objects.create(makerspace=space, max_reminders=0)
    new_charge(space, staff, due_at=now)
    assert run_reminder_sweep(now=now)["dispatched"] == 0


def test_settlement_and_foreign_subject_are_revalidated_before_dispatch(deliveries):
    space, staff = reminder_space("p6-scope-own")
    other, other_staff = reminder_space("p6-scope-other")
    now = timezone.now()
    payment = new_charge(other, other_staff, due_at=now)
    due, _ = _steps(other, payment)
    schedule_reminders(makerspace=space, source="payments.due", subject=str(payment.pk), kind="day:0", due_at=due)
    # Settle between schedule creation and dispatch; neither tenant may mail the row.
    from apps.payments.reconciliation import mark_offline
    from tests.return_helpers import settlement_details
    mark_offline(payment, other_staff, settlement_details())
    emails, _ = deliveries
    emails.clear()
    assert run_reminder_sweep(now=now)["dispatched"] == 0
    assert not emails
    assert ReminderSchedule.objects.get(makerspace=space).state == "completed"


@pytest.mark.parametrize("status,opted_out", [("revoked", False), ("active", True)])
def test_reminders_respect_member_revocation_and_opt_out(status, opted_out, deliveries):
    from apps.makerspaces.models import MakerspaceMembership
    space, staff = reminder_space("p6-member-preference")
    now = timezone.now()
    new_charge(space, staff, due_at=now)
    MakerspaceMembership.objects.filter(makerspace=space, user=staff).update(
        status=status, receives_notifications=not opted_out,
    )
    emails, channels = deliveries
    emails.clear()
    run_reminder_sweep(now=now)
    assert not emails and not channels


def test_small_discovery_batches_advance_beyond_scheduled_ladders(deliveries):
    space, staff = reminder_space("p6-batches")
    now = timezone.now()
    new_charge(space, staff, due_at=now)
    new_charge(space, make_member("p6-batch-second", space), due_at=now)
    for _ in range(10):
        run_reminder_sweep(now=now, limit=1)
    emails, _ = deliveries
    reminders = [row for row in emails if "payment_due_today" in row["text_body"]]
    assert len(reminders) == 2


def test_dst_steps_follow_local_calendar_days():
    space, staff = reminder_space("p6-dst")
    space.timezone = "America/New_York"
    space.save(update_fields=["timezone"])
    MakerspaceBillingSettings.objects.create(makerspace=space, reminder_days_before=[], reminder_days_after=[1])
    payment = new_charge(space, staff, due_at=datetime(2026, 3, 8, 15, tzinfo=utc.utc))
    _, offsets = _steps(space, payment)
    assert offsets == (0, 23 * 3600)


def test_payer_receipt_defaults_on_but_explicit_matrix_off_wins(deliveries):
    space = make_space("p6-receipt-default")
    staff = make_member("p6-receipt-staff", space)
    payment = new_charge(space, staff)
    from apps.payments.notifications import notify_payment
    emails, channels = deliveries
    notify_payment(payment, "payment_received")
    assert [row["to_email"] for row in emails] == [staff.email]
    assert emails[0]["audience"] == "requester" and not channels
    emails.clear()
    NotificationPreference.objects.create(makerspace=space, feature="payments", channel="email", enabled=False)
    notify_payment(payment, "payment_received")
    assert not emails


def test_receipt_correction_does_not_emit_second_refund_event(monkeypatch):
    _, staff, payment = cash_deposit("p6-refund-event")
    events = []
    monkeypatch.setattr("apps.payments.notifications.notify_payment", lambda payment, event, **kwargs: events.append(event))
    refund = record_offline_refund(payment, actor=staff, **payload("3.00"))
    amend_offline_refund(payment, actor=staff, refund_id=refund.pk, receipt=payload(reference="fixed")["receipt"])
    assert events == ["refund_issued"]
