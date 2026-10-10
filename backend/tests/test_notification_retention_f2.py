from datetime import timedelta
from uuid import uuid4

import pytest
from django.utils import timezone

from apps.integrations.models import EmailLog, NotificationDeliveryLog
from apps.notifications.models import NotificationInboxRow
from apps.notifications.retention import run_notification_retention, sweep_tenant_retention
from apps.operations import reminder_registry
from apps.operations.reminder_sweeper import run_reminder_sweep
from tests.return_helpers import make_member, make_space
from tests.tenant_migration.source_gate_helpers import close_gate, make_actor

pytestmark = pytest.mark.django_db(transaction=True)


def inbox(space, user, read_at):
    return NotificationInboxRow.objects.create(makerspace=space, user=user, event_key=uuid4(),
        feature="bookings", event="confirmed", title="Message", read_at=read_at)


def delivery(model, space, status, now, age):
    common = {"makerspace": space, "status": status}
    if model is EmailLog:
        common.update(to_email="member@example.test", subject="Old mail", text_body="Old body")
    else:
        common.update(channel="slack", feature="bookings", event="confirmed", text_body="Old message")
    row = model.objects.create(**common)
    model.objects.filter(pk=row.pk).update(created_at=now - timedelta(days=age),
        updated_at=now - timedelta(days=age), sent_at=now - timedelta(days=age) if status == "sent" else None)
    return row


def test_retention_keeps_unread_inflight_recent_failures_and_other_tenants():
    now = timezone.now()
    space, other = make_space("f2-retention"), make_space("f2-retention-other")
    user = make_member("f2-retention-member", space)
    old_read = inbox(space, user, now - timedelta(days=91))
    unread = inbox(space, user, None)
    fresh_read = inbox(space, user, now - timedelta(days=1))
    foreign = inbox(other, user, now - timedelta(days=91))
    gone, kept = [], []
    for model in (EmailLog, NotificationDeliveryLog):
        gone += [(model, delivery(model, space, "sent", now, 91).pk),
                 (model, delivery(model, space, "failed", now, 366).pk)]
        kept += [(model, delivery(model, space, status, now, age).pk)
                 for status, age in (("failed", 364), ("pending", 500), ("sending", 500), ("sent", 89))]
    assert sweep_tenant_retention(space, now=now, limit=100) == 5
    assert not NotificationInboxRow.objects.filter(pk=old_read.pk).exists()
    assert NotificationInboxRow.objects.filter(pk__in=[unread.pk, fresh_read.pk, foreign.pk]).count() == 3
    assert all(not model.objects.filter(pk=pk).exists() for model, pk in gone)
    assert all(model.objects.filter(pk=pk).exists() for model, pk in kept)


def test_f1_runs_retention_without_reminder_sources_and_batches_are_bounded(monkeypatch):
    now = timezone.now()
    space = make_space("f2-f1-retention")
    user = make_member("f2-f1-member", space)
    for _ in range(3):
        inbox(space, user, now - timedelta(days=100))
    monkeypatch.setattr(reminder_registry, "REMINDER_SOURCES", ())
    assert run_reminder_sweep(now=now, limit=1) == {"dispatched": 0, "skipped": 0, "failed": 0}
    assert NotificationInboxRow.objects.filter(makerspace=space).count() == 2
    run_reminder_sweep(now=now, limit=1)
    assert NotificationInboxRow.objects.filter(makerspace=space).count() == 1


@pytest.mark.django_db(transaction=False)
def test_targeted_missing_source_is_noop_without_global_retention(monkeypatch):
    calls = []
    monkeypatch.setattr(reminder_registry, "REMINDER_SOURCES", ())
    monkeypatch.setattr("apps.notifications.retention.run_notification_retention",
                        lambda **kwargs: calls.append(kwargs))
    assert run_reminder_sweep(source_keys=("loans.return", "loans.escalation")) == {
        "dispatched": 0, "skipped": 0, "failed": 0,
    }
    assert calls == []


def test_retention_respects_tenant_freeze():
    now = timezone.now()
    space = make_space("f2-retention-frozen")
    user = make_member("f2-frozen-user", space)
    row = inbox(space, user, now - timedelta(days=100))
    close_gate(space, make_actor("f2-freeze-actor"))
    counts = run_notification_retention(now=now, limit=10)
    assert counts["skipped"] >= 1
    assert NotificationInboxRow.objects.filter(pk=row.pk).exists()


def test_platform_email_retention_is_bounded_and_keeps_inflight_and_recent_failures():
    now = timezone.now()
    old = [delivery(EmailLog, None, "sent", now, 91) for _ in range(3)]
    failed = delivery(EmailLog, None, "failed", now, 366)
    recent = delivery(EmailLog, None, "failed", now, 364)
    pending = delivery(EmailLog, None, "pending", now, 500)
    skipped = delivery(EmailLog, None, "skipped", now, 91)
    counts = run_notification_retention(now=now, limit=2)
    assert counts["deleted"] == 2 and counts["failed"] == 0
    assert EmailLog.objects.filter(pk__in=[row.pk for row in old]).count() == 1
    run_notification_retention(now=now, limit=10)
    assert not EmailLog.objects.filter(pk__in=[old[-1].pk, failed.pk, skipped.pk]).exists()
    assert EmailLog.objects.filter(pk__in=[recent.pk, pending.pk]).count() == 2


@pytest.mark.parametrize("limit", [0, -1, True, 1.5])
def test_retention_rejects_invalid_batch_sizes_before_deleting_rows(limit):
    row = delivery(EmailLog, None, "sent", timezone.now(), 91)
    with pytest.raises(ValueError):
        run_notification_retention(now=timezone.now(), limit=limit)
    assert EmailLog.objects.filter(pk=row.pk).exists()
