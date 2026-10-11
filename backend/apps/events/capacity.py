import math
from datetime import timedelta

from apps.events.models import EventRegistration


CONFIRMED_STATUSES = (
    EventRegistration.Status.REGISTERED,
    EventRegistration.Status.ATTENDED,
)


def confirmed_occupancy(event):
    confirmed = getattr(event, 'confirmed_count', None)
    if confirmed is None:
        confirmed = event.registrations.filter(
            status__in=CONFIRMED_STATUSES
        ).count()
    return confirmed


def spots_left(event):
    if event.capacity == 0:
        return None
    return max(event.capacity - confirmed_occupancy(event), 0)


def availability_label(event):
    if event.capacity == 0:
        return 'Available'
    left = spots_left(event)
    if left <= 0:
        return 'Full'
    if left <= math.ceil(event.capacity * 0.2):
        return 'Limited'
    return 'Available'


def effective_registration_cutoff(event):
    if event.registration_cutoff_at is not None:
        return event.registration_cutoff_at
    if event.registration_cutoff_lead_minutes is not None:
        return event.starts_at - timedelta(
            minutes=event.registration_cutoff_lead_minutes
        )
    return None


def registration_is_open(event, now):
    if event.status != event.Status.PUBLISHED or now >= event.ends_at:
        return False
    cutoff = effective_registration_cutoff(event)
    return cutoff is None or now < cutoff


def ticket_spots_left(event, ticket):
    if ticket is None or ticket.capacity == 0:
        return None
    occupied = event.registrations.filter(ticket_type=ticket, status__in=CONFIRMED_STATUSES).count()
    return max(ticket.capacity - occupied, 0)


def registration_spots_left(event, ticket=None):
    limits = [value for value in (spots_left(event), ticket_spots_left(event, ticket)) if value is not None]
    return min(limits) if limits else None


def fresh_registration_status(event, ticket=None):
    if event.registration_requires_approval:
        return EventRegistration.Status.PENDING_APPROVAL
    available = registration_spots_left(event, ticket)
    if available is None or available > 0:
        return EventRegistration.Status.REGISTERED
    return EventRegistration.Status.WAITLISTED
