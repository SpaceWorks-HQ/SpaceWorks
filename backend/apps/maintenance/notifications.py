"""Lifecycle notification adapter for machine maintenance."""

from apps.integrations.destinations import NotificationScope
from apps.integrations.notify import EmailDelivery, LifecyclePayload, notify_lifecycle
from apps.integrations.staff_notifications import staff_emails_for_feature
from apps.maintenance.models import MaintenanceLog, MaintenanceSchedule


def _clamp(value, limit=300):
    text = str(value or "")
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _text(event_name, machine, schedule=None, log=None):
    lines = [
        f"Maintenance {event_name}.",
        f"Machine: {machine.name}",
    ]
    if schedule is not None:
        lines.extend(
            (
                f"Schedule: #{schedule.pk}",
                f"Description: {_clamp(schedule.description)}",
                f"Next due: {schedule.next_due}",
                f"Active: {schedule.is_active}",
            )
        )
    if log is not None:
        lines.extend(
            (
                f"Log: #{log.pk}",
                f"Summary: {_clamp(log.summary)}",
                f"Performed at: {log.performed_at}",
            )
        )
        if log.parts_note:
            lines.append(f"Parts note: {_clamp(log.parts_note)}")
    return "\n".join(lines)


def notify_maintenance_lifecycle(instance, event_name, *, log_id=None, sync=False):
    is_schedule = isinstance(instance, MaintenanceSchedule)
    object_id = instance.pk
    makerspace = instance.machine.makerspace

    def build():
        schedule = None
        log = None
        if is_schedule:
            schedule = MaintenanceSchedule.objects.select_related(
                "machine__makerspace"
            ).get(pk=object_id)
            machine = schedule.machine
            if log_id is not None:
                log = MaintenanceLog.objects.get(pk=log_id, machine=machine)
        else:
            log = MaintenanceLog.objects.select_related("machine__makerspace").get(
                pk=object_id
            )
            machine = log.machine
        text = _text(event_name, machine, schedule=schedule, log=log)
        subject = f"{makerspace.name} maintenance {event_name}: {machine.name}"
        emails = tuple(
            EmailDelivery(
                to_email=recipient,
                subject=subject,
                text_body=text,
                audience="staff",
                stream="maintenance",
            )
            for recipient in staff_emails_for_feature(
                makerspace, "maintenance", event=event_name
            )
        )
        # The machine is what makes per-machine chat rooms work: a destination scoped to
        # the laser (or to every 3D printer) matches on this, and an unscoped room still
        # receives everything.
        return LifecyclePayload(
            text=text, emails=emails, scope=NotificationScope(machine=machine)
        )

    return notify_lifecycle(
        makerspace,
        feature="maintenance",
        event=event_name,
        build=build,
        sync=sync,
    )
