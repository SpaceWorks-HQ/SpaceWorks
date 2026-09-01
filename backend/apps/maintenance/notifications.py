"""Lifecycle notification adapter for machine maintenance."""

from apps.integrations.destinations import NotificationScope
from apps.integrations.email_templates import render
from apps.integrations.email_templates_fablab import maintenance_context
from apps.integrations.email_templates_registry_fablab_defaults import (
    MAINTENANCE_REQUESTER_BODIES,
)
from apps.integrations.notify import EmailDelivery, LifecyclePayload, notify_lifecycle
from apps.integrations.staff_notifications import staff_emails_for_feature
from apps.maintenance.models import MaintenanceLog, MaintenanceSchedule


def notify_maintenance_lifecycle(instance, event_name, *, log_id=None, sync=False):
    is_schedule = isinstance(instance, MaintenanceSchedule)
    object_id = instance.pk
    makerspace = instance.machine.makerspace

    def build():
        schedule = None
        log = None
        if is_schedule:
            schedule = MaintenanceSchedule.objects.select_related(
                "machine__makerspace", "machine__machine_type"
            ).get(pk=object_id)
            machine = schedule.machine
            if log_id is not None:
                log = MaintenanceLog.objects.get(pk=log_id, machine=machine)
        else:
            log = MaintenanceLog.objects.select_related(
                "machine__makerspace", "machine__machine_type"
            ).get(
                pk=object_id
            )
            machine = log.machine
        context = maintenance_context(
            machine,
            event_name,
            schedule=schedule,
            log=log,
            next_steps=MAINTENANCE_REQUESTER_BODIES.get(event_name, ""),
        )
        # The machine is what makes per-machine routing work on both sides: a chat room
        # scoped to the laser (or to every 3D printer) matches on it, and a recipient rule
        # narrowed the same way filters who is mailed.
        scope = NotificationScope(machine=machine)
        staff = render(
            makerspace,
            "maintenance",
            "staff",
            event_name,
            context,
            machine_type=machine.machine_type,
        )
        emails = tuple(
            EmailDelivery(
                to_email=recipient,
                subject=staff["subject"],
                text_body=staff["text_body"],
                audience="staff",
                stream="maintenance",
            )
            for recipient in staff_emails_for_feature(
                makerspace, "maintenance", event=event_name, scope=scope
            )
        )
        # This text is also the no-ChatTemplate chat fallback and the native-push body.
        # A maintenance type override intentionally gives all three channels one wording.
        return LifecyclePayload(
            text=staff["text_body"],
            emails=emails,
            scope=scope,
            context=context,
        )

    return notify_lifecycle(
        makerspace,
        feature="maintenance",
        event=event_name,
        build=build,
        sync=sync,
    )
