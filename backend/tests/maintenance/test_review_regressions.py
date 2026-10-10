from datetime import date, datetime, timezone as utc

import pytest
from django.urls import reverse
from rest_framework.exceptions import PermissionDenied
from rest_framework.test import APIClient

from apps.audit.models import AuditLog
from apps.maintenance import reminders, services
from apps.maintenance.models import MaintenanceLog
from apps.operations.reminder_sweeper import run_reminder_sweep
from tests.maintenance.test_reminder_anchors import world
from tests.module_helpers import disable_module

pytestmark = pytest.mark.django_db(transaction=True)


def test_overdue_notices_take_priority_in_small_discovery_batches(monkeypatch):
    space, actor, machine = world("review-overdue-priority")
    now = datetime(2026, 10, 11, 10, tzinfo=utc.utc)
    advance = services.create_schedule(machine, actor=actor, description="Advance", interval_days=7,
                                       next_due=date(2026, 10, 12))
    overdue = services.create_schedule(machine, actor=actor, description="Overdue", interval_days=7,
                                       next_due=date(2026, 10, 1))
    seen = []
    monkeypatch.setattr(reminders, "notify_maintenance_lifecycle", lambda row, event: seen.append((row.pk, event)))
    run_reminder_sweep(now=now, limit=1)
    assert seen == [(overdue.pk, "overdue")]
    run_reminder_sweep(now=now, limit=1)
    assert seen == [(overdue.pk, "overdue"), (advance.pk, "due_soon")]


def test_foreign_actor_cannot_complete_schedule_through_service():
    space, actor, machine = world("review-foreign-completion")
    _, outsider, _ = world("review-foreign-completion-other")
    schedule = services.create_schedule(machine, actor=actor, description="PM", interval_days=7,
                                        next_due=date(2026, 10, 1))
    with pytest.raises(PermissionDenied):
        services.complete_due(schedule, actor=outsider, summary="Unauthorized")
    schedule.refresh_from_db()
    assert schedule.next_due == date(2026, 10, 1)
    assert not MaintenanceLog.objects.filter(machine=machine).exists()
    assert not AuditLog.objects.filter(action="maintenance.schedule_completed", makerspace=space).exists()


def test_schedule_http_surfaces_refuse_machines_off_with_400():
    space, actor, machine = world("review-module-off")
    schedule = services.create_schedule(machine, actor=actor, description="PM", interval_days=7,
                                        next_due=date(2026, 10, 1))
    disable_module(space, "machines")
    api = APIClient()
    api.force_authenticate(actor)
    url = reverse("admin-maintenance-schedule-list-create", args=[space.pk, machine.pk])
    assert api.get(url).status_code == 400
    assert api.post(url, {"description": "PM", "interval_days": 7, "next_due": "2026-10-12"}, format="json").status_code == 400
    url = reverse("admin-maintenance-schedule-detail", args=[schedule.pk])
    assert api.patch(url, {"anchor": "calendar"}, format="json").status_code == 400
