from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.maintenance import services
from apps.maintenance.meters import meter_due, readings
from apps.maintenance import reminders_meters
from apps.machines.models import MachineUsageEntry
from tests.maintenance.helpers import make_machine_setup

pytestmark = pytest.mark.django_db


def world(slug):
    space, actor, machine, _ = make_machine_setup(slug)
    space.enabled_features = sorted(set(space.enabled_features) | {"maintenance.meters", "maintenance.reminders"})
    space.save(update_fields=["enabled_features"])
    machine.makerspace = space
    return space, actor, machine


def test_usage_hours_derive_from_ledger_and_reset_on_completion():
    space, actor, machine = world("meter-hours")
    MachineUsageEntry.objects.create(machine=machine, hours=100)
    schedule = services.create_schedule(machine, actor=actor, description="Lubricate",
        interval_days=30, next_due=timezone.localdate()+timedelta(days=30), trigger="usage", usage_hours=Decimal("2"))
    assert not meter_due(schedule)
    MachineUsageEntry.objects.create(machine=machine, hours=Decimal("2.25"))
    assert meter_due(schedule) and readings(schedule)["hours"] == Decimal("2.25")
    services.complete_due(schedule, actor=actor, summary="Serviced")
    schedule.refresh_from_db()
    assert not meter_due(schedule)
    assert MachineUsageEntry.objects.filter(machine=machine).count() == 2


def test_job_trigger_counts_runs_and_calendar_remains_independent():
    _, actor, machine = world("meter-jobs")
    schedule = services.create_schedule(machine, actor=actor, description="Inspect",
        interval_days=30, next_due=timezone.localdate()-timedelta(days=1), trigger="both", job_count=2)
    MachineUsageEntry.objects.create(machine=machine, hours=10)
    assert not meter_due(schedule)
    MachineUsageEntry.objects.create(machine=machine, source="typed_manual", hours=1)
    MachineUsageEntry.objects.create(machine=machine, source="typed_manual", hours=1)
    assert meter_due(schedule)
    assert schedule in list(services.overdue_schedules())


def test_threshold_validation_and_feature_off_fail_400():
    space, actor, machine = world("meter-validation")
    with pytest.raises(ValidationError):
        services.create_schedule(machine, actor=actor, description="Invalid", interval_days=30,
            next_due=timezone.localdate(), trigger="usage")
    space.enabled_features = [key for key in space.enabled_features if key != "maintenance.meters"]
    space.save(update_fields=["enabled_features"])
    machine.makerspace = space
    with pytest.raises(ValidationError):
        services.create_schedule(machine, actor=actor, description="Disabled", interval_days=30,
            next_due=timezone.localdate(), trigger="usage", job_count=1)


def test_meter_reminder_is_tenant_scoped_and_occurrence_changes_on_completion(monkeypatch):
    space, actor, machine = world("meter-reminder")
    other, _, _ = world("meter-other")
    schedule = services.create_schedule(machine, actor=actor, description="Inspect", interval_days=30,
        next_due=timezone.localdate()+timedelta(days=30), trigger="usage", job_count=1)
    MachineUsageEntry.objects.create(machine=machine, source="typed_manual", hours=1)
    now = timezone.now()
    subject = next(iter(reminders_meters.discover(space, now, 10, ZoneInfo("UTC"))))
    reminder = SimpleNamespace(subject=subject.subject)
    assert reminders_meters.build(other, reminder, now, ZoneInfo("UTC")) is None
    message = reminders_meters.build(space, reminder, now, ZoneInfo("UTC"))
    assert message is not None
    sent = []
    monkeypatch.setattr(reminders_meters.reminders, "notify_maintenance_lifecycle",
                        lambda row, event, **kwargs: sent.append(kwargs["due_reason"]))
    reminders_meters.dispatch(space, reminder, message, now, ZoneInfo("UTC"))
    assert sent == ["Usage-based maintenance is due."]
    services.complete_due(schedule, actor=actor, summary="Done")
    assert reminders_meters.build(space, reminder, now, ZoneInfo("UTC")) is None


def test_service_minutes_and_jobs_include_terminal_runs_without_double_counting_linked_logs():
    from apps.machines.models import MachineServiceRequest, ServiceBucket
    from apps.maintenance.meters import due_queryset
    _, actor, machine = world("meter-services")
    schedule = services.create_schedule(machine, actor=actor, description="Inspect", interval_days=30,
        next_due=timezone.localdate()+timedelta(days=30), trigger="usage", usage_hours=Decimal("2"), job_count=1)
    bucket = ServiceBucket.objects.create(machine=machine, name="Jobs")
    run = MachineServiceRequest.objects.create(bucket=bucket, makerspace=machine.makerspace, requester=actor,
        assigned_machine=machine, title="Done", status="completed", completed_at=timezone.now(), actual_minutes=120)
    MachineUsageEntry.objects.create(machine=machine, hours=2, source="typed_manual", service_request=run)
    assert readings(schedule) == {"hours": Decimal("2"), "jobs": 1}
    assert meter_due(schedule)
    assert due_queryset(type(schedule).objects.filter(pk=schedule.pk), timezone.localdate()).exists()


def test_calendar_overdue_without_usage_does_not_starve_due_meter():
    space, actor, machine = world("meter-fairness")
    services.create_schedule(machine, actor=actor, description="Calendar only due", interval_days=30,
        next_due=timezone.localdate()-timedelta(days=1), trigger="both", job_count=100)
    due = services.create_schedule(machine, actor=actor, description="Meter due", interval_days=30,
        next_due=timezone.localdate()+timedelta(days=30), trigger="usage", job_count=1)
    MachineUsageEntry.objects.create(machine=machine, source="typed_manual", hours=1)
    subjects = list(reminders_meters.discover(space, timezone.now(), 1, ZoneInfo("UTC")))
    assert len(subjects) == 1 and subjects[0].subject.startswith(f"{due.pk}:")


def test_schedule_api_rejects_non_object_and_accepts_meter_with_audit():
    from django.urls import reverse
    from rest_framework.test import APIClient
    from apps.audit.models import AuditLog
    space, actor, machine = world("meter-api")
    client = APIClient()
    client.force_authenticate(actor)
    url = reverse("admin-maintenance-schedule-list-create", kwargs={"makerspace_id": space.pk, "machine_id": machine.pk})
    assert client.post(url, [{}], format="json").status_code == 400
    response = client.post(url, {"description": "Oil", "interval_days": 30,
        "next_due": str(timezone.localdate()), "trigger": "usage", "job_count": 2}, format="json")
    assert response.status_code == 201 and response.data["job_count"] == 2
    assert AuditLog.objects.filter(makerspace=space, actor=actor, action="maintenance.schedule_created").exists()
