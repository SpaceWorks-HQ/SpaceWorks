from datetime import date, datetime, timedelta, timezone as dt_timezone

import pytest
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.maintenance import services, services_workflows
from apps.maintenance.models import MaintenanceLog
from tests.maintenance.helpers import make_machine_setup


pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("due_offset", [-95, -60, -30, 0, 10])
def test_completion_starts_fresh_interval_and_audits_due_dates(due_offset, monkeypatch):
    completed_at = datetime(2026, 10, 10, 12, tzinfo=dt_timezone.utc)
    monkeypatch.setattr(timezone, "now", lambda: completed_at)
    with timezone.override("UTC"):
        makerspace, actor, machine, _ = make_machine_setup("completion-recurrence")
        today = completed_at.date()
        old_due = today + timedelta(days=due_offset)
        schedule = services.create_schedule(
            machine, actor=actor, description="Inspect", interval_days=30,
            next_due=old_due,
        )

        log = services.complete_due(schedule, actor=actor, summary="Inspected")

        schedule.refresh_from_db()
        assert log.performed_at == completed_at
        assert schedule.next_due == today + timedelta(days=30)
        assert not services.overdue_schedules(today=today).filter(pk=schedule.pk).exists()
        audit = AuditLog.objects.get(
            action="maintenance.schedule_completed", target_id=str(schedule.pk),
        )
        assert audit.actor == actor
        assert audit.makerspace == makerspace
        assert audit.meta == {
            "log_id": log.pk,
            "anchor": "completion",
            "old_next_due": old_due.isoformat(),
            "new_next_due": schedule.next_due.isoformat(),
            "interval_days": 30,
        }


@pytest.mark.parametrize(
    ("zone", "expected_due"),
    [("UTC", date(2026, 10, 9)), ("Asia/Kolkata", date(2026, 10, 10))],
)
def test_backdated_completion_uses_recorded_local_date(zone, expected_due, monkeypatch):
    entered_at = datetime(2026, 10, 10, 12, tzinfo=dt_timezone.utc)
    performed_at = datetime(2026, 10, 2, 23, 30, tzinfo=dt_timezone.utc)
    monkeypatch.setattr(timezone, "now", lambda: entered_at)
    with timezone.override(zone):
        space, actor, machine, _ = make_machine_setup("completion-backdated")
        space.timezone = zone
        space.save(update_fields=["timezone"])
        schedule = services.create_schedule(
            machine, actor=actor, description="Clean", interval_days=7,
            next_due=date(2026, 9, 1),
        )

        log = services.complete_due(
            schedule, actor=actor, summary="Cleaned earlier", performed_at=performed_at,
        )

        schedule.refresh_from_db()
        assert log.performed_at == performed_at
        assert schedule.next_due == expected_due


def test_completion_audit_failure_rolls_back_log_and_rescheduled_date(monkeypatch):
    _, actor, machine, _ = make_machine_setup("completion-rollback")
    old_due = timezone.localdate() - timedelta(days=90)
    schedule = services.create_schedule(
        machine, actor=actor, description="Check", interval_days=30, next_due=old_due,
    )
    original_record = services_workflows.record

    def fail_completion_audit(actor, action, **kwargs):
        if action == "maintenance.schedule_completed":
            raise RuntimeError("audit unavailable")
        return original_record(actor, action, **kwargs)

    monkeypatch.setattr(services_workflows, "record", fail_completion_audit)
    before_logs = MaintenanceLog.objects.count()
    before_audits = AuditLog.objects.count()

    with pytest.raises(RuntimeError, match="audit unavailable"):
        services.complete_due(schedule, actor=actor, summary="Must roll back")

    schedule.refresh_from_db()
    assert schedule.next_due == old_due
    assert MaintenanceLog.objects.count() == before_logs
    assert AuditLog.objects.count() == before_audits
