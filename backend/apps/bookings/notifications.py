"""Shared lifecycle adapter for booking notifications."""

from apps.bookings.models import Booking
from apps.integrations.email_templates import render
from apps.integrations.email_templates_fablab import bookings_context
from apps.integrations.email_templates_registry_fablab_defaults import (
    BOOKINGS_REQUESTER_BODIES,
)
from apps.integrations.notify import EmailDelivery, LifecyclePayload, notify_lifecycle
from apps.integrations.staff_notifications import staff_emails_for_feature

BOOKING_NOTIFICATION_EVENTS = frozenset(
    {"created", "confirmed", "rejected", "cancelled", "completed", "no_show"}
)


def _effective_toggle(booking):
    override = booking.space.requester_notifications_enabled
    if override is not None:
        return override
    return booking.space.makerspace.booking_requester_notifications_enabled


def notify_booking_status(booking, event, *, sync=False):
    booking_id = booking.pk
    makerspace = booking.space.makerspace

    def build():
        row = Booking.objects.select_related("space__makerspace").get(pk=booking_id)
        # One context, both audiences: the wording differs per template, the facts do not.
        context = bookings_context(
            row, event, next_steps=BOOKINGS_REQUESTER_BODIES.get(event, "")
        )
        emails = []
        if _effective_toggle(row) and row.email:
            member = render(makerspace, "bookings", "requester", event, context)
            emails.append(
                EmailDelivery(
                    to_email=row.email,
                    subject=member["subject"],
                    text_body=member["text_body"],
                    html_body=member["html_body"],
                    audience="requester",
                    stream="bookings",
                )
            )
        staff = render(makerspace, "bookings", "staff", event, context)
        emails.extend(
            EmailDelivery(
                to_email=recipient,
                subject=staff["subject"],
                text_body=staff["text_body"],
                audience="staff",
                stream="bookings",
            )
            for recipient in staff_emails_for_feature(
                makerspace, "bookings", event=event
            )
        )
        # `text` is the STAFF body: chat channels are a staff surface, so the member's
        # "your booking is confirmed" wording must never be what reaches a room.
        return LifecyclePayload(
            text=staff["text_body"], emails=tuple(emails), context=context
        )

    return notify_lifecycle(
        makerspace,
        feature="bookings",
        event=event,
        build=build,
        sync=sync,
    )
