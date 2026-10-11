"""Review regressions: live gates, valid fixtures and concurrent full sweeps."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from threading import Barrier
from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError
from django.db import close_old_connections, connection
from django.utils import timezone

from apps.accounts import rbac
from apps.backup.models import B1RestoreComponentState
from apps.bookings.models import BookableSpace, Booking
from apps.makerspaces.models import Makerspace
from apps.notifications.models import Notification
from apps.operations import reminder_registry, reminder_sweeper
from apps.operations.models import ReminderSchedule
from apps.operations.reminder_services import claim_reminders, complete_reminder, schedule_reminders
from tests.module_helpers import disable_module
from tests.operations.reminder_example import EXAMPLE_SOURCE
from tests.return_helpers import make_space

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture(autouse=True)
def example_source(monkeypatch):
    monkeypatch.setattr(reminder_registry, "REMINDER_SOURCES", (EXAMPLE_SOURCE,))


def _booking(space, now):
    room = BookableSpace.objects.create(makerspace=space, name="Review room")
    return Booking.objects.create(
        space=room, name="Review", email="review@example.test", phone="1234567890",
        starts_at=now, ends_at=now + timedelta(hours=1),
    )


def _schedule(space, booking, now, **extra):
    return schedule_reminders(
        makerspace=space, source=EXAMPLE_SOURCE.key, subject=str(booking.pk),
        kind=extra.pop("kind", "starts"), due_at=now, **extra,
    )


def test_sweep_with_manually_disabled_autocommit_is_refused():
    now = timezone.now()
    space = make_space("sweep-manual-transaction")
    _booking(space, now)
    connection.set_autocommit(False)
    try:
        with pytest.raises(RuntimeError, match="autocommit"):
            reminder_sweeper.run_reminder_sweep(now=now)
    finally:
        connection.rollback()
        connection.set_autocommit(True)
    assert not ReminderSchedule.objects.exists()
    assert not Notification.objects.exists()


@pytest.mark.parametrize("changes", [
    {"superadmin_access_enabled": False},
    {"lifecycle_state": Makerspace.LifecycleState.IMPORTING},
    {"archived_at": "now"},
])
def test_background_scope_excludes_unavailable_tenants_and_direct_writes(changes):
    now = timezone.now()
    space, live = make_space("sweep-unavailable"), make_space("sweep-available")
    booking = _booking(space, now)
    _booking(live, now)
    row, = _schedule(space, booking, now)
    claimed, = claim_reminders(makerspace=space, source=EXAMPLE_SOURCE.key, now=now)
    updates = {key: now if value == "now" else value for key, value in changes.items()}
    Makerspace.objects.filter(pk=space.pk).update(**updates)

    assert set(rbac.scope_for_scheduled_work(
        Makerspace.objects.all(), field="pk",
    ).values_list("pk", flat=True)) == {live.pk}
    assert reminder_sweeper.run_reminder_sweep(now=now) == {
        "dispatched": 1, "skipped": 0, "failed": 0,
    }
    with pytest.raises(ValidationError, match="unavailable"):
        _schedule(space, booking, now, offsets=(86400,))
    with pytest.raises(ValidationError, match="unavailable"):
        claim_reminders(makerspace=space, source=EXAMPLE_SOURCE.key, now=now)
    with pytest.raises(ValidationError, match="unavailable"):
        complete_reminder(makerspace=space, reminder_id=row.pk, claim_token=claimed.claim_token)
    row.refresh_from_db()
    assert row.state == ReminderSchedule.State.CLAIMED
    assert ReminderSchedule.objects.filter(makerspace=space).count() == 1
    assert not Notification.objects.filter(makerspace=space).exists()


def test_not_restored_tenant_reaches_the_gate_and_is_counted():
    now = timezone.now()
    pending, live = make_space("sweep-not-restored"), make_space("sweep-restored")
    booking = _booking(pending, now)
    row, = _schedule(pending, booking, now)
    _booking(live, now)
    from tests.backup.test_not_restored_state_e7 import _operation, _component
    _component(_operation(), pending.pk)
    assert reminder_sweeper.run_reminder_sweep(now=now) == {
        "dispatched": 1, "skipped": 1, "failed": 0,
    }
    row.refresh_from_db()
    assert row.state == ReminderSchedule.State.PENDING
    assert not Notification.objects.filter(makerspace=pending).exists()


@pytest.mark.parametrize("gate", ["bookings", "notifications", "feature"])
def test_source_disabled_during_discovery_is_not_claimed(monkeypatch, gate):
    now = timezone.now()
    space = make_space("sweep-gate-changed")
    booking = _booking(space, now)
    row, = _schedule(space, booking, now)
    space.enabled_features = sorted(set(space.enabled_features) | {"mobile.push"})
    space.save(update_fields=["enabled_features"])

    def discover(makerspace, *args):
        subjects = list(EXAMPLE_SOURCE.discover(makerspace, *args))
        if gate == "feature":
            makerspace.enabled_features = [key for key in makerspace.enabled_features if key != "mobile.push"]
            makerspace.save(update_fields=["enabled_features"])
        else:
            disable_module(makerspace, gate)
        return subjects

    monkeypatch.setattr(reminder_registry, "REMINDER_SOURCES", (
        replace(EXAMPLE_SOURCE, discover=discover, feature="mobile.push" if gate == "feature" else None),
    ))
    assert reminder_sweeper.run_reminder_sweep(now=now) == {
        "dispatched": 0, "skipped": 1, "failed": 0,
    }
    row.refresh_from_db()
    assert row.state == ReminderSchedule.State.PENDING
    assert not Notification.objects.exists()


def test_source_disabled_during_build_is_not_dispatched(monkeypatch):
    now = timezone.now()
    space = make_space("sweep-build-gate-changed")
    _booking(space, now)

    def build(makerspace, *args):
        message = EXAMPLE_SOURCE.build(makerspace, *args)
        disable_module(makerspace, "bookings")
        return message

    monkeypatch.setattr(reminder_registry, "REMINDER_SOURCES", (
        replace(EXAMPLE_SOURCE, build=build),
    ))
    assert reminder_sweeper.run_reminder_sweep(now=now) == {
        "dispatched": 0, "skipped": 1, "failed": 0,
    }
    assert ReminderSchedule.objects.get(makerspace=space).state == ReminderSchedule.State.COMPLETED
    assert not Notification.objects.exists()


def test_wrong_kind_and_removed_offset_are_revalidated_before_dispatch():
    now = timezone.now()
    space = make_space("sweep-wrong-kind")
    booking = _booking(space, now)
    _schedule(space, booking, now, kind="unsupported")
    _schedule(space, booking, now, offsets=(-1,))
    assert reminder_sweeper.run_reminder_sweep(now=now) == {
        "dispatched": 1, "skipped": 2, "failed": 0,
    }
    assert Notification.objects.filter(makerspace=space).count() == 1


def test_two_concurrent_sweeps_dispatch_the_same_subject_once(monkeypatch):
    now = timezone.now()
    space = make_space("sweep-concurrent")
    _booking(space, now)
    ready = Barrier(2)

    def discover(makerspace, *args):
        subjects = list(EXAMPLE_SOURCE.discover(makerspace, *args))
        ready.wait(timeout=15)
        return subjects

    monkeypatch.setattr(reminder_registry, "REMINDER_SOURCES", (
        replace(EXAMPLE_SOURCE, discover=discover),
    ))

    def worker():
        close_old_connections()
        try:
            return reminder_sweeper.run_reminder_sweep(now=now)
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: worker(), range(2)))
    assert sum(result["dispatched"] for result in results) == 1
    assert sum(result["failed"] for result in results) == 0
    assert ReminderSchedule.objects.get(makerspace=space).state == ReminderSchedule.State.COMPLETED
    assert Notification.objects.filter(makerspace=space).count() == 1


@pytest.mark.parametrize("changes", [{"key": " "}, {"feature": ""}, {"build": None}])
def test_invalid_source_declarations_are_refused(monkeypatch, changes):
    monkeypatch.setattr(reminder_registry, "REMINDER_SOURCES", (replace(EXAMPLE_SOURCE, **changes),))
    with pytest.raises(ValueError):
        reminder_registry.registered_sources()
