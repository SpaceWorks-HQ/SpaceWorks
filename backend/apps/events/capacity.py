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


def fresh_registration_status(event):
    if event.registration_requires_approval:
        return EventRegistration.Status.PENDING_APPROVAL
    available = spots_left(event)
    if available is None or available > 0:
        return EventRegistration.Status.REGISTERED
    return EventRegistration.Status.WAITLISTED
