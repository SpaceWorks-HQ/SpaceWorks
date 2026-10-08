"""notifications channels and `reports` x the modules they read (matrix N4, N11, N12, N13, N15).

The matrix GET omits a channel whose module is uninstalled, the destination API refuses a
room on one, and the manual export refuses a report whose source module is off. Three
write paths had not caught up: the matrix PATCH, and a report schedule's destination
and report key. Each stored a state that could only ever skip.
"""

from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.integrations.models import NotificationPreference
from apps.integrations.models_destinations import NotificationDestination
from apps.operations.models import ReportSchedule
from apps.operations.report_registry import REPORT_DEFINITIONS
from apps.operations.report_schedule_services import run_report_schedules
from tests.module_helpers import disable_module
from tests.return_helpers import authenticated_client, make_member, make_space

pytestmark = pytest.mark.django_db


def _rules_url(space):
    return f"/api/v1/admin/makerspace/{space.id}/notification-rules"


def _schedules_url(space):
    return f"/api/v1/admin/makerspaces/{space.id}/report-schedules"


def test_matrix_patch_cannot_switch_on_a_channel_whose_module_is_uninstalled():
    space = make_space("combo-matrix-patch")
    manager = make_member("combo-matrix-patch-mgr", space)
    client = authenticated_client(manager)
    disable_module(space, "slack")

    on = client.patch(
        _rules_url(space),
        {"preferences": [{"feature": "events", "channel": "slack", "enabled": True}]},
        format="json",
    )
    off = client.patch(
        _rules_url(space),
        {"preferences": [{"feature": "events", "channel": "slack", "enabled": False}]},
        format="json",
    )

    assert on.status_code == 400 and "slack" in str(on.data)
    assert off.status_code == 200, off.data
    assert not NotificationPreference.objects.filter(
        makerspace=space, channel="slack", enabled=True
    ).exists()


def test_matrix_patch_still_switches_on_an_installed_channel():
    space = make_space("combo-matrix-patch-on")
    client = authenticated_client(make_member("combo-matrix-patch-on-mgr", space))

    response = client.patch(
        _rules_url(space),
        {"preferences": [{"feature": "events", "channel": "slack", "enabled": True}]},
        format="json",
    )

    assert response.status_code == 200, response.data
    assert NotificationPreference.objects.get(makerspace=space, channel="slack").enabled


def test_schedule_refuses_a_room_on_an_uninstalled_channel():
    space = make_space("combo-sched-room")
    client = authenticated_client(make_member("combo-sched-room-mgr", space))
    room = NotificationDestination.objects.create(
        makerspace=space, channel="telegram", label="Ops", telegram_chat_id="-100",
    )
    body = {"report_key": "most-lent", "format": "csv", "cadence": "daily", "destination": room.id}
    assert client.post(_schedules_url(space), body, format="json").status_code == 201

    disable_module(space, "telegram")
    response = client.post(_schedules_url(space), body, format="json")

    assert response.status_code == 400
    assert "telegram" in str(response.data)


def test_schedule_refuses_a_report_whose_source_module_is_off():
    space = make_space("combo-sched-source")
    client = authenticated_client(make_member("combo-sched-source-mgr", space))
    body = {
        "report_key": "booking-utilization", "format": "csv", "cadence": "weekly",
        "recipient_emails": ["ops@example.test"],
    }
    assert client.post(_schedules_url(space), body, format="json").status_code == 201

    disable_module(space, "bookings")
    response = client.post(_schedules_url(space), body, format="json")

    assert response.status_code == 400
    assert "bookings is disabled" in str(response.data)


def test_a_schedule_whose_source_module_goes_away_later_is_skipped_and_audited():
    space = make_space("combo-sched-skip")
    manager = make_member("combo-sched-skip-mgr", space)
    schedule = ReportSchedule.objects.create(
        makerspace=space, report_key="booking-utilization", format="csv", cadence="daily",
        next_run_at=timezone.now() - timedelta(minutes=1), created_by=manager,
        recipient_emails=["ops@example.test"],
    )
    disable_module(space, "bookings")

    run_report_schedules()

    skipped = AuditLog.objects.get(action="report_schedule.skipped", target_id=str(schedule.pk))
    assert skipped.meta["reason"] == "module_disabled:bookings"
    assert not schedule.deliveries.exists()


GATED_REPORTS = tuple(
    (definition.key, definition.required_modules[0])
    for definition in REPORT_DEFINITIONS
    if definition.required_modules and not definition.summary
)


@pytest.mark.parametrize(("report_key", "module"), GATED_REPORTS)
def test_every_gated_report_refuses_with_its_source_module_off(report_key, module):
    space = make_space(f"combo-report-{report_key}")
    manager = make_member(f"combo-report-{report_key}-mgr", space)
    space.enabled_modules = [key for key in space.enabled_modules if key != module]
    space.save(update_fields=["enabled_modules"])

    response = authenticated_client(manager).get(
        reverse("analytics-generic", args=[space.id, report_key])
    )

    assert response.status_code == 400, (report_key, response.status_code)
    assert f"{module} is disabled" in str(response.data)
