from datetime import date, datetime, timedelta, timezone as utc
from zoneinfo import ZoneInfo

import pytest
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework.exceptions import ValidationError

from apps.audit.models import AuditLog
from apps.maintenance import services, reminders
from apps.maintenance.models import MaintenanceSchedule
from apps.machines.models import MakerspaceMachineTypePolicy
from apps.operations.models_reminders import ReminderSchedule
from apps.operations.reminder_sweeper import run_reminder_sweep
from tests.maintenance.helpers import make_machine_setup
from tests.module_helpers import disable_module

pytestmark = pytest.mark.django_db(transaction=True)


def world(slug, zone="UTC"):
    space, actor, machine, _ = make_machine_setup(slug)
    space.timezone = zone
    space.enabled_features = sorted(set(space.enabled_features) | {"maintenance.reminders"})
    space.enabled_modules = sorted(set(space.enabled_modules) | {"notifications"})
    space.save(update_fields=["timezone", "enabled_features", "enabled_modules"])
    machine.makerspace = space
    return space, actor, machine


@pytest.mark.parametrize("old_due,completed,expected", [
    (date(2026, 1, 1), date(2026, 4, 10), date(2026, 5, 1)),
    (date(2026, 1, 1), date(2026, 1, 31), date(2026, 3, 2)),
    (date(2026, 1, 31), date(2026, 1, 10), date(2026, 3, 2)),
])
def test_fixed_calendar_preserves_phase_and_skips_missed_intervals(old_due, completed, expected):
    space, actor, machine = world("anchor-calendar")
    schedule = services.create_schedule(machine, actor=actor, description="PM", interval_days=30,
                                        next_due=old_due, anchor="calendar")
    services.complete_due(schedule, actor=actor, summary="PM complete",
                          performed_at=datetime.combine(completed, datetime.min.time(), tzinfo=utc.utc))
    schedule.refresh_from_db()
    assert schedule.next_due == expected and schedule.next_due > completed
    audit = AuditLog.objects.get(action="maintenance.schedule_completed", target_id=str(schedule.pk))
    assert audit.actor == actor and audit.meta["anchor"] == "calendar"


def test_completion_anchor_uses_makerspace_zone_not_worker_timezone():
    space, actor, machine = world("anchor-local", "Asia/Kolkata")
    schedule = services.create_schedule(machine, actor=actor, description="PM", interval_days=7,
                                        next_due=date(2026, 10, 1))
    services.complete_due(schedule, actor=actor, summary="Complete", performed_at=datetime(2026, 10, 11, 23, tzinfo=utc.utc))
    schedule.refresh_from_db()
    assert schedule.anchor == "completion" and schedule.next_due == date(2026, 10, 19)


def test_invalid_anchor_is_rejected_at_service_and_http_boundary():
    space, actor, machine = world("anchor-invalid")
    with pytest.raises(ValidationError):
        services.create_schedule(machine, actor=actor, description="PM", interval_days=7,
                                 next_due=date(2026, 10, 1), anchor="unknown")
    api = APIClient()
    api.force_authenticate(actor)
    # Use the existing canonical schedule collection path, not a new surface.
    response = api.post(reverse("admin-maintenance-schedule-list-create", args=[space.pk, machine.pk]),
                        {"description": "PM", "interval_days": 7, "next_due": "2026-10-01", "anchor": "unknown"}, format="json")
    assert response.status_code == 400
    assert not MaintenanceSchedule.objects.filter(machine=machine).exists()


def test_due_soon_and_overdue_are_once_per_occurrence_and_completion_rearms(monkeypatch):
    space, actor, machine = world("maint-remind", "Asia/Kolkata")
    now = datetime(2026, 10, 11, 18, 40, tzinfo=utc.utc)  # October 12 locally
    schedule = services.create_schedule(machine, actor=actor, description="PM", interval_days=7,
                                        next_due=date(2026, 10, 19))
    notices = []
    monkeypatch.setattr(reminders, "notify_maintenance_lifecycle", lambda row, event: notices.append((row.pk, event)))
    run_reminder_sweep(now=now)
    run_reminder_sweep(now=now)
    assert notices == [(schedule.pk, "due_soon")]
    marker = ReminderSchedule.objects.get(source=reminders.SOURCE, kind="due_soon", makerspace=space)
    assert marker.due_at == datetime(2026, 10, 11, 18, 30, tzinfo=utc.utc)
    overdue_now = datetime(2026, 10, 19, 18, 40, tzinfo=utc.utc)
    run_reminder_sweep(now=overdue_now)
    run_reminder_sweep(now=overdue_now)
    assert notices[-1] == (schedule.pk, "overdue") and len(notices) == 2
    services.complete_due(schedule, actor=actor, summary="PM", performed_at=overdue_now)
    run_reminder_sweep(now=overdue_now)
    assert len(notices) == 3 and notices[-1][1] == "due_soon"


def test_grace_period_deactivation_and_foreign_subject_revalidation():
    space, actor, machine = world("maint-grace")
    other, _, _ = world("maint-grace-other")
    MakerspaceMachineTypePolicy.objects.create(makerspace=space, machine_type=machine.machine_type, grace_days=2)
    schedule = services.create_schedule(machine, actor=actor, description="PM", interval_days=30, next_due=date(2026, 10, 10))
    now = datetime(2026, 10, 12, 12, tzinfo=utc.utc)
    assert [row for row in reminders.discover(space, now, 100, ZoneInfo("UTC")) if row.kind == "overdue"] == []
    due = reminders.reminder_time(space, schedule, "overdue")
    assert due == datetime(2026, 10, 13, tzinfo=utc.utc)
    marker = ReminderSchedule(subject=f"{schedule.pk}:2026-10-10", kind="overdue", due_at=due, offset_seconds=0)
    assert reminders.build(other, marker, due, ZoneInfo("UTC")) is None
    services.deactivate_schedule(schedule, actor=actor)
    assert reminders.build(space, marker, due, ZoneInfo("UTC")) is None


@pytest.mark.parametrize("module", ["machines", "maintenance", "notifications"])
def test_module_off_leaves_sweeper_inert(module, monkeypatch):
    space, actor, machine = world("maint-off-" + module)
    services.create_schedule(machine, actor=actor, description="PM", interval_days=7, next_due=date(2026, 10, 1))
    disable_module(space, module)
    calls = []
    monkeypatch.setattr(reminders, "notify_maintenance_lifecycle", lambda *a: calls.append(a))
    run_reminder_sweep(now=datetime(2026, 10, 11, tzinfo=utc.utc))
    assert calls == [] and not ReminderSchedule.objects.filter(makerspace=space).exists()


def test_small_batch_is_not_starved_by_a_disabled_advance_notice():
    space, actor, machine = world("maint-batch")
    MakerspaceMachineTypePolicy.objects.create(makerspace=space, machine_type=machine.machine_type, reminder_lead_days=0)
    services.create_schedule(machine, actor=actor, description="No advance", interval_days=7, next_due=date(2026, 10, 12))
    from apps.machines.models import Machine, MachineType
    kind = MachineType.objects.create(makerspace=space, slug="batch-other", name="Other")
    other_machine = Machine.objects.create(makerspace=space, machine_type=kind, name="Other machine")
    expected = services.create_schedule(other_machine, actor=actor, description="Advance", interval_days=7, next_due=date(2026, 10, 13))
    subjects = list(reminders.discover(space, datetime(2026, 10, 11, tzinfo=utc.utc), 1, ZoneInfo("UTC")))
    assert len(subjects) == 1 and subjects[0].subject.startswith(f"{expected.pk}:")
