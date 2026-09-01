import pytest
from django.test import override_settings
from django.utils import timezone

from apps.integrations import notify
from apps.integrations.models import (
    EmailLog,
    MachineTypeEmailTemplate,
    NotificationPreference,
)
from apps.machines.models import Machine, MachineType
from apps.maintenance import notifications, services, services_workflows
from apps.maintenance.models import MaintenanceLog
from tests.maintenance.helpers import make_machine_setup

pytestmark = pytest.mark.django_db


def test_each_maintenance_service_lifecycle_reaches_fanout_once(monkeypatch):
    calls = []
    monkeypatch.setattr(
        services_workflows,
        "notify_maintenance_lifecycle",
        lambda instance, name, **kwargs: calls.append((name, kwargs)),
    )
    _, manager, machine, _ = make_machine_setup("maintenance-fanout")
    services.log_maintenance(machine, actor=manager, summary="Cleaned")
    schedule = services.create_schedule(
        machine,
        actor=manager,
        description="Monthly",
        interval_days=30,
        next_due=timezone.localdate(),
    )
    services.update_schedule(schedule, actor=manager, description="Quarterly")
    services.complete_due(schedule, actor=manager, summary="Completed")
    services.deactivate_schedule(schedule, actor=manager)

    assert [name for name, _ in calls] == [
        "logged",
        "schedule_created",
        "schedule_updated",
        "schedule_completed",
        "schedule_deactivated",
    ]
    assert set(calls[3][1]) == {"log_id"}


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
def test_maintenance_notifications_are_silent_until_email_cell_enabled(monkeypatch):
    makerspace, manager, machine, _ = make_machine_setup("maintenance-pref")
    log = MaintenanceLog.objects.create(
        machine=machine,
        performed_by=manager,
        summary="Checked belts",
        parts_note="No replacement needed",
    )
    monkeypatch.setattr(
        notifications,
        "staff_emails_for_feature",
        lambda *args, **kwargs: ["maintenance@example.com"],
    )
    silent = notifications.notify_maintenance_lifecycle(log, "logged", sync=True)
    assert silent.delivered_counts == {}

    NotificationPreference.objects.create(
        makerspace=makerspace,
        feature="maintenance",
        channel="email",
        enabled=True,
    )
    delivered = notifications.notify_maintenance_lifecycle(log, "logged", sync=True)
    assert delivered.delivered_counts == {"email": 1}


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
def test_maintenance_alerts_render_the_actual_machine_type_override(monkeypatch):
    makerspace, manager, laser, _ = make_machine_setup("maintenance-type-render")
    printer_type = MachineType.objects.get(makerspace__isnull=True, slug="3d_printer")
    printer = Machine.objects.create(
        makerspace=makerspace, machine_type=printer_type, name="Printer",
        type_payload={"model": "MK4"},
    )
    for machine_type, label in ((laser.machine_type, "LASER"), (printer_type, "PRINTER")):
        MachineTypeEmailTemplate.objects.create(
            makerspace=makerspace, machine_type=machine_type, stream="maintenance",
            audience="staff", key="logged", subject=label,
            text_body=f"{label} {{{{ machine.name }}}}",
        )
    NotificationPreference.objects.create(
        makerspace=makerspace, feature="maintenance", channel="email", enabled=True
    )
    monkeypatch.setattr(
        notifications, "staff_emails_for_feature", lambda *args, **kwargs: ["staff@example.test"]
    )

    notifications.notify_maintenance_lifecycle(
        MaintenanceLog.objects.create(machine=laser, performed_by=manager, summary="Laser"),
        "logged", sync=True,
    )
    notifications.notify_maintenance_lifecycle(
        MaintenanceLog.objects.create(machine=printer, performed_by=manager, summary="Printer"),
        "logged", sync=True,
    )

    assert list(EmailLog.objects.filter(stream="maintenance").values_list(
        "subject", flat=True
    )) == ["PRINTER", "LASER"]


def test_maintenance_type_override_drives_chat_fallback_and_native_push(monkeypatch):
    makerspace, manager, machine, _ = make_machine_setup("maintenance-type-channels")
    MachineTypeEmailTemplate.objects.create(
        makerspace=makerspace, machine_type=machine.machine_type, stream="maintenance",
        audience="staff", key="logged", subject="Type subject",
        text_body="TYPE CHANNEL WORDING {{ machine.name }}",
    )
    for channel in ("slack", "native_push"):
        NotificationPreference.objects.create(
            makerspace=makerspace, feature="maintenance", channel=channel, enabled=True
        )
    calls = []
    monkeypatch.setattr(notify, "dispatch_channel", lambda **kwargs: calls.append(kwargs) or [])

    log = MaintenanceLog.objects.create(machine=machine, performed_by=manager, summary="Done")
    notifications.notify_maintenance_lifecycle(log, "logged", sync=True)

    bodies = {call["channel"]: call["text_body"] for call in calls}
    assert bodies["slack"] == f"TYPE CHANNEL WORDING {machine.name}"
    assert bodies["native_push"] == f"TYPE CHANNEL WORDING {machine.name}"
