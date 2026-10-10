"""Shared presentation and locked-service policy for member cancellation."""

from datetime import timedelta

from django.utils import timezone

from apps.events.models import Event, EventRegistration


def cancellation_cutoff(event):
    return event.starts_at - timedelta(hours=event.cancellation_cutoff_hours or 0)


def member_can_cancel(registration, *, now=None):
    return (
        registration.event.status == Event.Status.PUBLISHED
        and registration.status in (
            EventRegistration.Status.PENDING_APPROVAL,
            EventRegistration.Status.REGISTERED,
            EventRegistration.Status.WAITLISTED,
        )
        and (now or timezone.now()) < cancellation_cutoff(registration.event)
    )
