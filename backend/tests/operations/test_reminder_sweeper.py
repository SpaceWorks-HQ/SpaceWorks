from dataclasses import replace
from datetime import timedelta
from zoneinfo import ZoneInfo

import pytest
from django.db import connection
from django.utils import timezone

from apps.bookings.models import BookableSpace, Booking
from apps.notifications.models import Notification
from apps.operations import reminder_registry, reminder_services, reminder_sweeper
from apps.operations.models import ReminderSchedule
from apps.operations.reminder_services import schedule_reminders
from apps.operations.tasks_reminders import run_reminder_sweep_task
from tests.module_helpers import disable_module
from tests.operations.reminder_example import EXAMPLE_SOURCE
from tests.return_helpers import make_space
from tests.tenant_migration.source_gate_helpers import close_gate, make_actor

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture(autouse=True)
def example_source(monkeypatch):
    monkeypatch.setattr(reminder_registry, "REMINDER_SOURCES", (EXAMPLE_SOURCE,))


def _booking(space, now):
    room = BookableSpace.objects.create(makerspace=space, name="Example room")
    return Booking.objects.create(space=room, name="Example", email="example@example.test",
                                  phone="1234567890", starts_at=now,
                                  ends_at=now + timedelta(hours=1))


def test_two_sweeps_emit_once_and_complete_the_schedule():
    now = timezone.now()
    space = make_space("sweep-once")
    booking = _booking(space, now)
    assert reminder_sweeper.run_reminder_sweep(now=now)["dispatched"] == 1
    assert reminder_sweeper.run_reminder_sweep(now=now)["dispatched"] == 0
    row = ReminderSchedule.objects.get(makerspace=space, subject=str(booking.pk))
    assert row.state == ReminderSchedule.State.COMPLETED
    assert Notification.objects.filter(makerspace=space, event="example.booking.starts").count() == 1


def test_discovery_batches_do_not_starve_later_subjects():
    now = timezone.now()
    space = make_space("sweep-discovery-batches")
    _booking(space, now)
    _booking(space, now)
    assert reminder_sweeper.run_reminder_sweep(now=now, limit=1)["dispatched"] == 1
    assert reminder_sweeper.run_reminder_sweep(now=now, limit=1)["dispatched"] == 1
    assert reminder_sweeper.run_reminder_sweep(now=now, limit=1)["dispatched"] == 0
    assert Notification.objects.filter(makerspace=space).count() == 2


def test_emitter_runs_after_the_claim_transaction_commits(monkeypatch):
    now = timezone.now()
    space = make_space("sweep-io-autocommit")
    _booking(space, now)

    def emit(makerspace, **payload):
        assert not connection.in_atomic_block
        assert ReminderSchedule.objects.get(makerspace=makerspace).state == ReminderSchedule.State.CLAIMED

    monkeypatch.setattr(reminder_sweeper, "emit_notification", emit)
    assert reminder_sweeper.run_reminder_sweep(now=now)["dispatched"] == 1


def test_sweep_reuses_its_tenant_boundary_without_reacquiring_on_another_connection(monkeypatch):
    now = timezone.now()
    space = make_space("sweep-reuse-boundary")
    _booking(space, now)

    def unexpected_gate(*args, **kwargs):
        raise AssertionError("sweep must reuse its existing tenant gate")

    monkeypatch.setattr(reminder_services, "tenant_write", unexpected_gate)
    assert reminder_sweeper.run_reminder_sweep(now=now) == {
        "dispatched": 1, "skipped": 0, "failed": 0,
    }
    assert ReminderSchedule.objects.get(makerspace=space).state == ReminderSchedule.State.COMPLETED


def test_tenant_isolation_revalidates_a_foreign_subject():
    now = timezone.now()
    space, other = make_space("sweep-own"), make_space("sweep-other")
    booking = _booking(other, now)
    schedule_reminders(makerspace=space, source=EXAMPLE_SOURCE.key,
                       subject=str(booking.pk), kind="starts", due_at=now)
    counts = reminder_sweeper.run_reminder_sweep(now=now)
    assert counts == {"dispatched": 1, "skipped": 1, "failed": 0}
    assert not Notification.objects.filter(makerspace=space).exists()
    assert Notification.objects.filter(makerspace=other).count() == 1


@pytest.mark.parametrize("module", ["bookings", "notifications"])
def test_module_off_skips_discovery_and_leaves_pending_rows(module):
    now = timezone.now()
    space = make_space("sweep-module-off")
    booking = _booking(space, now)
    row, = schedule_reminders(makerspace=space, source=EXAMPLE_SOURCE.key,
                             subject=str(booking.pk), kind="starts", due_at=now)
    disable_module(space, module)
    assert reminder_sweeper.run_reminder_sweep(now=now) == {
        "dispatched": 0, "skipped": 1, "failed": 0,
    }
    row.refresh_from_db()
    assert row.state == ReminderSchedule.State.PENDING
    assert not Notification.objects.filter(makerspace=space).exists()


def test_feature_off_skips_a_source(monkeypatch):
    space = make_space("sweep-feature-off")
    now = timezone.now()
    _booking(space, now)
    # Use a real registered feature, rather than invent a production feature key.
    source = replace(EXAMPLE_SOURCE, feature="mobile.push")
    monkeypatch.setattr(reminder_registry, "REMINDER_SOURCES", (source,))
    space.enabled_features = [key for key in space.enabled_features if key != "mobile.push"]
    space.save(update_fields=["enabled_features"])
    assert reminder_sweeper.run_reminder_sweep(now=now)["skipped"] == 1
    assert not ReminderSchedule.objects.filter(makerspace=space).exists()


def test_gate_closed_tenant_is_skipped_and_counted_while_other_tenant_runs():
    now = timezone.now()
    frozen, live = make_space("sweep-frozen"), make_space("sweep-live")
    booking = _booking(frozen, now)
    row, = schedule_reminders(makerspace=frozen, source=EXAMPLE_SOURCE.key,
                             subject=str(booking.pk), kind="starts", due_at=now)
    _booking(live, now)
    close_gate(frozen, make_actor())
    assert reminder_sweeper.run_reminder_sweep(now=now) == {
        "dispatched": 1, "skipped": 1, "failed": 0,
    }
    row.refresh_from_db()
    assert row.state == ReminderSchedule.State.PENDING
    assert not Notification.objects.filter(makerspace=frozen).exists()


def test_cancelled_subject_is_rechecked_before_dispatch():
    now = timezone.now()
    space = make_space("sweep-cancelled")
    booking = _booking(space, now)
    row, = schedule_reminders(makerspace=space, source=EXAMPLE_SOURCE.key,
                             subject=str(booking.pk), kind="starts", due_at=now)
    Booking.objects.filter(pk=booking.pk).update(status=Booking.Status.CANCELLED)
    assert reminder_sweeper.run_reminder_sweep(now=now) == {
        "dispatched": 0, "skipped": 1, "failed": 0,
    }
    row.refresh_from_db()
    assert row.state == ReminderSchedule.State.COMPLETED
    assert not Notification.objects.filter(makerspace=space).exists()


def test_invalid_timezone_for_one_tenant_does_not_stop_other_tenants():
    now = timezone.now()
    broken, live = make_space("sweep-tz-broken"), make_space("sweep-tz-live")
    _booking(broken, now)
    _booking(live, now)
    counts = reminder_sweeper.run_reminder_sweep(
        now=now, tz_resolver=lambda space: None if space.pk == broken.pk else "UTC",
    )
    assert counts == {"dispatched": 1, "skipped": 0, "failed": 1}


def test_one_failing_tenant_does_not_stop_the_sweep(monkeypatch):
    now = timezone.now()
    broken, live = make_space("sweep-broken"), make_space("sweep-still-live")
    _booking(broken, now)
    _booking(live, now)

    def discover(space, *args):
        if space.pk == broken.pk:
            raise RuntimeError("subject source unavailable")
        return EXAMPLE_SOURCE.discover(space, *args)

    monkeypatch.setattr(reminder_registry, "REMINDER_SOURCES", (
        replace(EXAMPLE_SOURCE, discover=discover),
    ))
    assert reminder_sweeper.run_reminder_sweep(now=now) == {
        "dispatched": 1, "skipped": 0, "failed": 1,
    }


def test_dispatch_failure_is_terminal_and_does_not_retry(monkeypatch):
    now = timezone.now()
    space = make_space("sweep-dispatch-fails")
    _booking(space, now)
    calls = []

    def fail(*args, **kwargs):
        calls.append(True)
        raise RuntimeError("emitter unavailable")

    monkeypatch.setattr(reminder_sweeper, "emit_notification", fail)
    assert reminder_sweeper.run_reminder_sweep(now=now)["failed"] == 1
    assert reminder_sweeper.run_reminder_sweep(now=now)["failed"] == 0
    assert calls == [True]
    assert ReminderSchedule.objects.get(makerspace=space).state == ReminderSchedule.State.FAILED


def test_default_and_optional_timezone_resolvers_keep_utc_instants(monkeypatch, settings):
    now = timezone.now()
    space = make_space("sweep-timezone")
    _booking(space, now)
    seen = []

    def discover(space, instant, limit, local_tz):
        seen.append((instant.utcoffset(), str(local_tz)))
        return EXAMPLE_SOURCE.discover(space, instant, limit, local_tz)

    monkeypatch.setattr(reminder_registry, "REMINDER_SOURCES", (
        replace(EXAMPLE_SOURCE, discover=discover),
    ))
    settings.TIME_ZONE = "Asia/Kolkata"
    reminder_sweeper.run_reminder_sweep(now=now)
    reminder_sweeper.run_reminder_sweep(now=now, tz_resolver=lambda _: ZoneInfo("America/New_York"))
    assert seen == [(timedelta(0), "Asia/Kolkata"), (timedelta(0), "America/New_York")]
    assert ReminderSchedule.objects.get(makerspace=space).due_at == now


def test_empty_production_registry_is_a_noop(monkeypatch):
    monkeypatch.setattr(reminder_registry, "REMINDER_SOURCES", ())
    assert run_reminder_sweep_task() == {"dispatched": 0, "skipped": 0, "failed": 0}


def test_duplicate_and_unknown_registrations_are_refused(monkeypatch):
    monkeypatch.setattr(reminder_registry, "REMINDER_SOURCES", (EXAMPLE_SOURCE, EXAMPLE_SOURCE))
    with pytest.raises(ValueError, match="Duplicate"):
        reminder_registry.registered_sources()
    monkeypatch.setattr(reminder_registry, "REMINDER_SOURCES", (
        replace(EXAMPLE_SOURCE, module="unknown-module"),
    ))
    with pytest.raises(ValueError, match="Unknown"):
        reminder_registry.registered_sources()
