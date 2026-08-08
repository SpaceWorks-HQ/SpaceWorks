"""Lifecycle notification adapter for events and registrations."""

from apps.events.models import Event, EventRegistration
from apps.integrations.email_templates import render
from apps.integrations.email_templates_fablab import events_context
from apps.integrations.email_templates_registry_fablab_defaults import (
    EVENTS_REQUESTER_BODIES,
)
from apps.integrations.notify import EmailDelivery, LifecyclePayload, notify_lifecycle
from apps.integrations.staff_notifications import staff_emails_for_feature


def notify_event_lifecycle(
    event_obj, event_name, registration_id=None, *, sync=False
):
    event_id = event_obj.pk
    makerspace = event_obj.makerspace

    def build():
        event = Event.objects.select_related("makerspace").get(pk=event_id)
        registration = None
        if registration_id is not None:
            registration = EventRegistration.objects.get(
                pk=registration_id,
                event=event,
            )
        context = events_context(
            event,
            event_name,
            registration,
            next_steps=EVENTS_REQUESTER_BODIES.get(event_name, ""),
        )
        staff = render(makerspace, "events", "staff", event_name, context)
        emails = tuple(
            EmailDelivery(
                to_email=recipient,
                subject=staff["subject"],
                text_body=staff["text_body"],
                audience="staff",
                stream="events",
            )
            for recipient in staff_emails_for_feature(
                makerspace, "events", event=event_name
            )
        )
        return LifecyclePayload(
            text=staff["text_body"], emails=emails, context=context
        )

    return notify_lifecycle(
        makerspace,
        feature="events",
        event=event_name,
        build=build,
        sync=sync,
    )
