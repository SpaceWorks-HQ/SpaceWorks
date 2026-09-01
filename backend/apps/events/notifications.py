"""Lifecycle notification adapter for events and registrations."""

import logging

from apps.events.models import Event, EventRegistration
from apps.integrations.email_templates import render
from apps.integrations.email_templates_fablab import events_context
from apps.integrations.email_templates_registry_fablab_defaults import (
    EVENTS_REQUESTER_BODIES,
)
from apps.integrations.notify import EmailDelivery, LifecyclePayload, notify_lifecycle
from apps.integrations.staff_notifications import staff_emails_for_feature
from apps.makerspaces.servability import servable_q
from apps.organizations.models import OrganizationMakerspace


logger = logging.getLogger(__name__)


def _notify_makerspace(
    event_id, makerspace, event_name, registration_id, *, sync
):
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


def notify_event_lifecycle(
    event_obj, event_name, registration_id=None, *, sync=False
):
    event_id = event_obj.pk
    venue = event_obj.makerspace
    try:
        venue_result = _notify_makerspace(
            event_id, venue, event_name, registration_id, sync=sync
        )
    except Exception:
        logger.warning(
            "event_venue_notification_failed",
            extra={"event_id": event_id, "makerspace_id": venue.pk},
        )
        venue_result = None
    if registration_id is None:
        return venue_result

    # is_active on the organization is a KILL SWITCH: it confers no organizer authority, so
    # it must stop this fan-out too. A registration notification carries the registrant's
    # name, so continuing to deliver it to a deactivated organization's spaces would keep
    # leaking member PII to an organization that has been switched off. Unservable and
    # hard-hidden makerspaces are excluded for the same reason they are excluded from
    # organization-derived authority.
    organizer_spaces = (
        OrganizationMakerspace.objects.filter(
            servable_q("makerspace"),
            organization__organized_events__event_id=event_id,
            organization__is_active=True,
            makerspace__superadmin_access_enabled=True,
        )
        .exclude(makerspace_id=venue.pk)
        .select_related("makerspace")
        .order_by("makerspace_id")
        .distinct()
    )
    delivered_to = {venue.pk}
    for link in organizer_spaces:
        if link.makerspace_id in delivered_to:
            continue
        delivered_to.add(link.makerspace_id)
        try:
            _notify_makerspace(
                event_id,
                link.makerspace,
                event_name,
                registration_id,
                sync=sync,
            )
        except Exception:
            # notify_lifecycle is already fail-safe. Keep this boundary too so a future
            # adapter regression cannot let one organizer suppress the remaining spaces.
            logger.warning(
                "event_organizer_notification_failed",
                extra={"event_id": event_id, "makerspace_id": link.makerspace_id},
            )
    return venue_result


def notify_series_lifecycle(series_obj, event_name, *, sync=False):
    """Send one bounded lifecycle message for a series, never one per occurrence."""
    occurrence = series_obj.occurrences.order_by("starts_at", "pk").first()
    if occurrence is None:
        return None
    try:
        return _notify_makerspace(
            occurrence.pk, series_obj.makerspace, event_name, None, sync=sync
        )
    except Exception:
        logger.warning(
            "event_series_notification_failed",
            extra={"series_id": series_obj.pk, "makerspace_id": series_obj.makerspace_id},
        )
        return None
