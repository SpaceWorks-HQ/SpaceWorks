"""Transactional registration lifecycle transitions."""

from django.db import transaction
from django.utils import timezone

from apps.events.capacity import spots_left
from apps.events.exceptions import CapacityConflict, EventInvalidTransition
from apps.events.models import (
    Event,
    EventAttendanceCertificate,
    EventCheckInEvent,
    EventRegistration,
)
from apps.events.service_payments import (
    cancel_for_registration,
    create_for_registered_registration,
)
from apps.events.services_calendar import calendar_registration_changed


def _boundary():
    # Imported lazily so services.py can retain the established public import boundary.
    from apps.events import services

    return services


def _lock_registration(event, registration_id):
    registration = EventRegistration.objects.select_for_update().get(pk=registration_id)
    if registration.event_id != event.pk:
        raise EventInvalidTransition("Registration does not belong to this event.")
    registration.event = event
    return registration


def _decision_is_open(event):
    return event.status == Event.Status.PUBLISHED and timezone.now() < event.ends_at


def _lock_waiters(event):
    return list(
        EventRegistration.objects.select_for_update()
        .filter(event=event, status=EventRegistration.Status.WAITLISTED)
        .order_by("created_at", "id")
    )


def _promote(event, actor, waiters, count=None, *, mode):
    services = _boundary()
    selected = waiters if count is None else waiters[:count]
    for registration in selected:
        registration.event = event
        registration.status = EventRegistration.Status.REGISTERED
        registration.save(update_fields=["status"])
        calendar_registration_changed(registration)
        create_for_registered_registration(registration, actor)
        meta = {"registration_id": registration.pk, "promotion_mode": mode}
        services._audit(
            event, actor, "event.registration_promoted", registration, meta
        )
        services.notify_event_lifecycle(
            event, "registration_promoted", registration.pk
        )
    return selected


def promote_automatically(event, actor, count=None):
    if event.registration_requires_approval:
        return []
    return _promote(
        event, actor, _lock_waiters(event), count, mode="automatic_fifo"
    )


@transaction.atomic
def approve_registration(registration, *, actor):
    services = _boundary()
    event = services._locked_event(registration.event_id)
    locked = _lock_registration(event, registration.pk)
    if (
        not event.registration_requires_approval
        or locked.status != EventRegistration.Status.PENDING_APPROVAL
        or not _decision_is_open(event)
    ):
        raise EventInvalidTransition("This registration cannot be approved.")
    available = spots_left(event)
    new_status = (
        EventRegistration.Status.REGISTERED
        if available is None or available > 0
        else EventRegistration.Status.WAITLISTED
    )
    locked.status = new_status
    locked.save(update_fields=["status"])
    calendar_registration_changed(locked)
    if new_status == EventRegistration.Status.REGISTERED:
        create_for_registered_registration(locked, actor)
    services._audit(
        event,
        actor,
        "event.registration_approved",
        locked,
        {
            "registration_id": locked.pk,
            "old_status": EventRegistration.Status.PENDING_APPROVAL,
            "new_status": new_status,
            "capacity_result": (
                "confirmed" if new_status == EventRegistration.Status.REGISTERED
                else "waitlisted_full"
            ),
        },
    )
    services.notify_event_lifecycle(event, "registration_approved", locked.pk)
    return services._refresh(locked)


@transaction.atomic
def reject_registration(registration, *, actor):
    services = _boundary()
    event = services._locked_event(registration.event_id)
    locked = _lock_registration(event, registration.pk)
    if locked.status not in (
        EventRegistration.Status.PENDING_APPROVAL,
        EventRegistration.Status.WAITLISTED,
    ):
        raise EventInvalidTransition("This registration cannot be rejected.")
    old_status = locked.status
    locked.status = EventRegistration.Status.REJECTED
    locked.save(update_fields=["status"])
    calendar_registration_changed(locked)
    services._audit(
        event,
        actor,
        "event.registration_rejected",
        locked,
        {
            "registration_id": locked.pk,
            "old_status": old_status,
            "new_status": EventRegistration.Status.REJECTED,
        },
    )
    services.notify_event_lifecycle(event, "registration_rejected", locked.pk)
    return services._refresh(locked)


@transaction.atomic
def promote_registration(registration, *, actor):
    services = _boundary()
    event = services._locked_event(registration.event_id)
    locked = _lock_registration(event, registration.pk)
    if (
        not event.registration_requires_approval
        or locked.status != EventRegistration.Status.WAITLISTED
        or not _decision_is_open(event)
    ):
        raise EventInvalidTransition("This registration cannot be promoted manually.")
    available = spots_left(event)
    if available is not None and available <= 0:
        raise CapacityConflict("No event capacity is available.")
    return services._refresh(
        _promote(event, actor, [locked], 1, mode="manual")[0]
    )


@transaction.atomic
def cancel_registration(registration, *, actor=None):
    services = _boundary()
    event = services._locked_event(registration.event_id)
    locked = _lock_registration(event, registration.pk)
    if locked.status not in (
        EventRegistration.Status.PENDING_APPROVAL,
        EventRegistration.Status.REGISTERED,
        EventRegistration.Status.WAITLISTED,
    ):
        raise EventInvalidTransition("This registration cannot be cancelled.")
    old_status = locked.status
    locked.status = EventRegistration.Status.CANCELLED
    locked.save(update_fields=["status"])
    calendar_registration_changed(locked)
    services._audit(
        event,
        actor,
        "event.registration_cancelled",
        locked,
        {"registration_id": locked.pk, "old_status": old_status},
    )
    services.notify_event_lifecycle(event, "registration_cancelled", locked.pk)
    cancel_for_registration(locked, actor)
    if (
        old_status == EventRegistration.Status.REGISTERED
        and not event.registration_requires_approval
        and event.capacity > 0
        and services._may_promote(event, timezone.now())
    ):
        promote_automatically(event, actor, 1)
    return services._refresh(locked)


@transaction.atomic
def mark_attended(
    registration,
    *,
    actor,
    source=EventCheckInEvent.Source.STAFF,
):
    services = _boundary()
    event = services._locked_event(registration.event_id)
    locked = _lock_registration(event, registration.pk)
    if (
        locked.status != EventRegistration.Status.REGISTERED
        or event.status not in (Event.Status.PUBLISHED, Event.Status.COMPLETED)
    ):
        raise EventInvalidTransition("This registration cannot be marked attended.")
    locked.status = EventRegistration.Status.ATTENDED
    locked.save(update_fields=["status"])
    check_in = EventCheckInEvent.objects.create(
        registration=locked,
        source=source,
        attended_at=timezone.now(),
        recorded_by=actor,
    )
    services._audit(
        event,
        actor,
        "event.registration_attended",
        locked,
        {
            "registration_id": locked.pk,
            "check_in_event_id": check_in.pk,
            "source": source,
        },
    )
    services.notify_event_lifecycle(event, "registration_attended", locked.pk)
    return services._refresh(locked)


@transaction.atomic
def correct_attendance(registration, *, actor):
    services = _boundary()
    event = services._locked_event(registration.event_id)
    locked = _lock_registration(event, registration.pk)
    if locked.status != EventRegistration.Status.ATTENDED:
        raise EventInvalidTransition("Only attended registrations can be corrected.")
    certificates = list(
        EventAttendanceCertificate.objects.select_for_update().filter(
            registration=locked,
            status=EventAttendanceCertificate.Status.ACTIVE,
        )
    )
    locked.status = EventRegistration.Status.REGISTERED
    locked.save(update_fields=["status"])
    now = timezone.now()
    for certificate in certificates:
        certificate.status = EventAttendanceCertificate.Status.REVOKED
        certificate.revoked_at = now
        certificate.revoked_by = actor
        certificate.revocation_reason = (
            EventAttendanceCertificate.RevocationReason.ATTENDANCE_CORRECTED
        )
        certificate.save(
            update_fields=[
                "status", "revoked_at", "revoked_by", "revocation_reason",
            ]
        )
        services._audit(
            event,
            actor,
            "event.certificate_revoked",
            certificate,
            {"reason": certificate.revocation_reason, "revision": certificate.revision},
        )
    services._audit(
        event,
        actor,
        "event.registration_attendance_corrected",
        locked,
        {"registration_id": locked.pk, "revoked_certificates": len(certificates)},
    )
    return services._refresh(locked), certificates
