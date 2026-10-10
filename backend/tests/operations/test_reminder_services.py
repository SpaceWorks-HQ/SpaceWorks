"""Coordination semantics; the coordinator must run against isolated Postgres."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone as utc
from threading import Barrier, Event
from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError
from django.db import close_old_connections, connection, transaction
from django.db.models import QuerySet
from django.utils import timezone

from apps.operations.models import ReminderSchedule
from apps.operations.reminder_services import (
    claim_reminders, complete_reminder, schedule_reminders,
)
from apps.tenant_migration.gate_errors import SourceMigrationGateClosed
from tests.return_helpers import make_space
from tests.tenant_migration.source_gate_helpers import close_gate, make_actor

pytestmark = pytest.mark.django_db(transaction=True)


def _schedule(space, **overrides):
    values = dict(makerspace=space, source="test.booking", subject="booking:1",
                  kind="starts", due_at=timezone.now() - timedelta(days=1), offsets=(0,))
    values.update(overrides)
    return schedule_reminders(**values)


def test_offsets_are_utc_and_duplicate_steps_are_idempotent():
    space = make_space("reminder-offsets")
    due_at = datetime(2026, 10, 10, 12, tzinfo=utc(timedelta(hours=5, minutes=30)))
    offsets = [-3 * 86400, -86400, 0, 86400, 7 * 86400, 0]
    first = _schedule(space, due_at=due_at, offsets=offsets)
    second = _schedule(space, due_at=due_at, offsets=offsets)
    assert [row.pk for row in first] == [row.pk for row in second]
    assert len(first) == 5
    for row in first:
        assert row.due_at == due_at.astimezone(utc.utc)
        assert row.remind_at == due_at.astimezone(utc.utc) + timedelta(seconds=row.offset_seconds)


def test_changed_due_time_moves_only_pending_rows():
    space = make_space("reminder-change")
    old_due = timezone.now() - timedelta(hours=1)
    _schedule(space, due_at=old_due, offsets=(0, 86400))
    claimed, = claim_reminders(makerspace=space, source="test.booking")
    new_due = old_due + timedelta(days=3)
    _schedule(space, due_at=new_due, offsets=(0, 86400))
    claimed.refresh_from_db()
    pending = ReminderSchedule.objects.get(makerspace=space, offset_seconds=86400)
    assert claimed.due_at == old_due
    assert pending.due_at == new_due
    assert pending.remind_at == new_due + timedelta(days=1)


def test_each_offset_waits_for_its_own_due_instant():
    space = make_space("reminder-step-times")
    due = timezone.now()
    _schedule(space, due_at=due, offsets=(-86400, 0, 86400))
    assert not claim_reminders(makerspace=space, source="test.booking",
                               now=due-timedelta(days=2))
    for now, expected_offset in (
        (due-timedelta(days=1), -86400), (due, 0), (due+timedelta(days=1), 86400),
    ):
        row, = claim_reminders(makerspace=space, source="test.booking", now=now)
        assert row.offset_seconds == expected_offset
        complete_reminder(makerspace=space, reminder_id=row.pk,
                          claim_token=row.claim_token, now=now)


def test_claim_and_complete_are_fenced_idempotent_and_tenant_scoped():
    space, other = make_space("reminder-own"), make_space("reminder-other")
    row, = _schedule(space)
    other_row, = _schedule(other)
    claimed, = claim_reminders(makerspace=space, source="test.booking")
    assert claimed.pk == row.pk
    assert not claim_reminders(makerspace=space, source="test.booking")
    args = dict(reminder_id=claimed.pk, claim_token=claimed.claim_token)
    assert not complete_reminder(makerspace=other, **args)
    assert not complete_reminder(makerspace=space, **{**args, "claim_token": uuid4()})
    assert complete_reminder(makerspace=space, **args)
    completed_at = ReminderSchedule.objects.get(pk=row.pk).completed_at
    assert complete_reminder(makerspace=space, now=timezone.now()+timedelta(hours=1), **args)
    assert ReminderSchedule.objects.get(pk=row.pk).completed_at == completed_at
    other_row.refresh_from_db()
    assert other_row.state == ReminderSchedule.State.PENDING


def test_committed_claim_is_never_reclaimed_even_after_a_crash():
    space = make_space("reminder-no-retry")
    _schedule(space)
    row, = claim_reminders(makerspace=space, source="test.booking")
    assert not claim_reminders(makerspace=space, source="test.booking",
                               now=timezone.now()+timedelta(days=100))
    assert complete_reminder(makerspace=space, reminder_id=row.pk,
                             claim_token=row.claim_token, failed=True)
    assert not claim_reminders(makerspace=space, source="test.booking")


def test_standalone_primitives_refuse_a_closed_tenant():
    space = make_space("reminder-direct-closed")
    _schedule(space)
    row, = claim_reminders(makerspace=space, source="test.booking")
    close_gate(space, make_actor())
    with pytest.raises(SourceMigrationGateClosed):
        _schedule(space, subject="second")
    with pytest.raises(SourceMigrationGateClosed):
        claim_reminders(makerspace=space, source="test.booking")
    with pytest.raises(SourceMigrationGateClosed):
        complete_reminder(makerspace=space, reminder_id=row.pk, claim_token=row.claim_token)
    row.refresh_from_db()
    assert row.state == ReminderSchedule.State.CLAIMED
    assert ReminderSchedule.objects.filter(makerspace=space).count() == 1


@pytest.mark.parametrize("overrides", [
    {"due_at": datetime(2026, 10, 10)}, {"offsets": [True]}, {"offsets": [1.5]},
    {"offsets": "1d"}, {"offsets": [2**31]}, {"subject": ""}, {"kind": "x" * 81},
    {"source": " "}, {"offsets": list(range(101))},
    {"due_at": datetime.max.replace(tzinfo=utc.utc), "offsets": [1]},
    {"due_at": datetime.max.replace(tzinfo=utc(timedelta(hours=-5)))},
])
def test_invalid_schedule_inputs_are_refused_without_rows(overrides):
    space = make_space("reminder-invalid")
    with pytest.raises(ValidationError):
        _schedule(space, **overrides)
    assert not ReminderSchedule.objects.filter(makerspace=space).exists()


def test_claim_inside_an_outer_transaction_is_refused():
    space = make_space("reminder-autocommit")
    _schedule(space)
    with transaction.atomic(), pytest.raises(RuntimeError, match="autocommit"):
        claim_reminders(makerspace=space, source="test.booking")


def test_claim_with_manually_disabled_autocommit_is_refused():
    space = make_space("reminder-manual-transaction")
    _schedule(space)
    connection.set_autocommit(False)
    try:
        with pytest.raises(RuntimeError, match="autocommit"):
            claim_reminders(makerspace=space, source="test.booking")
    finally:
        connection.rollback()
        connection.set_autocommit(True)
    assert ReminderSchedule.objects.get(makerspace=space).state == ReminderSchedule.State.PENDING


@pytest.mark.parametrize("invalid_now", [0, False, "", datetime(2026, 10, 10)])
def test_invalid_claim_and_completion_times_are_refused(invalid_now):
    space = make_space("reminder-invalid-time")
    row, = _schedule(space)
    with pytest.raises(ValidationError, match="timezone-aware"):
        claim_reminders(makerspace=space, source="test.booking", now=invalid_now)
    with pytest.raises(ValidationError, match="timezone-aware"):
        complete_reminder(makerspace=space, reminder_id=row.pk, claim_token=uuid4(), now=invalid_now)
    row.refresh_from_db()
    assert row.state == ReminderSchedule.State.PENDING


def test_two_workers_claim_distinct_rows():
    space = make_space("reminder-race")
    for index in range(4):
        _schedule(space, subject=f"booking:{index}")
    ready = Barrier(2)

    def worker():
        close_old_connections()
        try:
            ready.wait(timeout=15)
            return {row.pk for row in claim_reminders(
                makerspace=space, source="test.booking", limit=2,
            )}
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: worker(), range(2)))
    assert len(results[0]) == len(results[1]) == 2
    assert results[0].isdisjoint(results[1])
    assert set.union(*results) == set(ReminderSchedule.objects.values_list("pk", flat=True))


def test_claim_skips_a_row_locked_by_another_worker():
    space = make_space("reminder-locked")
    first, = _schedule(space, subject="first")
    second, = _schedule(space, subject="second")
    locked, release = Event(), Event()

    def holder():
        close_old_connections()
        try:
            with transaction.atomic():
                ReminderSchedule.objects.select_for_update().get(pk=first.pk)
                locked.set()
                assert release.wait(timeout=15)
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(holder)
        assert locked.wait(timeout=15)
        try:
            # Bound accidental blocking so a missing skip_locked fails promptly.
            with connection.cursor() as cursor:
                cursor.execute("SET lock_timeout = '2s'")
            claimed = claim_reminders(makerspace=space, source="test.booking", limit=2)
            assert [row.pk for row in claimed] == [second.pk]
        finally:
            with connection.cursor() as cursor:
                cursor.execute("RESET lock_timeout")
            release.set()
        future.result(timeout=15)


def test_visibility_change_during_claim_cannot_return_an_unpersisted_token(monkeypatch):
    space = make_space("reminder-claim-visibility-race")
    row, = _schedule(space)
    selected, changed = Event(), Event()
    original = QuerySet.bulk_update

    def update(queryset, objects, fields, **kwargs):
        if queryset.model is ReminderSchedule:
            selected.set()
            assert changed.wait(timeout=15)
        return original(queryset, objects, fields, **kwargs)

    def hide_tenant():
        close_old_connections()
        try:
            assert selected.wait(timeout=15)
            type(space).objects.filter(pk=space.pk).update(superadmin_access_enabled=False)
            changed.set()
        finally:
            close_old_connections()

    monkeypatch.setattr(QuerySet, "bulk_update", update)
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(hide_tenant)
        with pytest.raises(ValidationError, match="changed while claiming"):
            claim_reminders(makerspace=space, source="test.booking")
        future.result(timeout=15)
    row.refresh_from_db()
    assert row.state == ReminderSchedule.State.PENDING
    assert row.claim_token is None
