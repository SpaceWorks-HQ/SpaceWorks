"""Lifecycle notification adapter for machine maintenance."""

from apps.integrations.destinations import NotificationScope
from apps.accounts import rbac
from apps.integrations.email_templates import render
from apps.integrations.email_templates_fablab import maintenance_context
from apps.integrations.email_templates_registry_fablab_defaults import (
    MAINTENANCE_REQUESTER_BODIES,
)
from apps.integrations.notify import EmailDelivery, LifecyclePayload, notify_lifecycle
from apps.integrations.staff_notifications import staff_emails_for_feature
from apps.maintenance.models import MaintenanceLog, MaintenanceSchedule


def notify_maintenance_lifecycle(instance, event_name, *, log_id=None, sync=False, due_reason=""):
    is_schedule = isinstance(instance, MaintenanceSchedule)
    object_id = instance.pk
    makerspace = instance.machine.makerspace

    def build():
        from apps.integrations.recipients import feature_available
        from apps.makerspaces.servability import is_servable
        makerspace.refresh_from_db()
        if not is_servable(makerspace) or not feature_available(makerspace, "maintenance"):
            raise ValueError("Maintenance notifications are unavailable.")
        def rows(model):
            queryset = model.objects.all()
            if event_name in ("due_soon", "overdue"):
                return rbac.scope_for_scheduled_work(
                    queryset, makerspace_id=makerspace.pk, field="machine__makerspace_id",
                )
            return queryset
        schedule = None
        log = None
        if is_schedule:
            schedule = rows(MaintenanceSchedule).select_related(
                "machine__makerspace", "machine__machine_type"
            ).get(pk=object_id)
            machine = schedule.machine
            if log_id is not None:
                log = rows(MaintenanceLog).get(pk=log_id, machine=machine)
        else:
            log = rows(MaintenanceLog).select_related(
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
            next_steps=due_reason or MAINTENANCE_REQUESTER_BODIES.get(event_name, ""),
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
        text_body = f"{due_reason}\n\n{staff['text_body']}" if due_reason else staff["text_body"]
        emails = tuple(
            EmailDelivery(
                to_email=recipient,
                subject=staff["subject"],
                text_body=text_body,
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
            text=text_body,
            emails=emails,
            scope=scope,
            context=context,
            data={
                "machine_id": machine.pk,
                "schedule_id": schedule.pk if schedule else None,
                "maintenance_log_id": log.pk if log else None,
            },
        )

    return notify_lifecycle(
        makerspace,
        feature="maintenance",
        event=event_name,
        build=build,
        sync=sync,
    )
