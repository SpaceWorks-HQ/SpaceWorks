from django.db import transaction
from django.utils import timezone

from apps.events.exceptions import EventInvalidTransition
from apps.events.models import (
    Event,
    EventAttendanceCertificate,
    EventFeedbackSurvey,
)
from apps.events.services_calendar import calendar_event_changed
from apps.makerspaces import limits
from apps.makerspaces.guards import require_module_locked


def _boundary():
    from apps.events import services

    return services


def _transition(event, actor, expected, new_status, action):
    services = _boundary()
    locked = services._locked_event(event.pk)
    if locked.status != expected:
        message = f"Cannot transition event from {locked.status} to {new_status}."
        raise EventInvalidTransition(message)
    locked.status = new_status
    locked.save(update_fields=["status", "updated_at"])
    calendar_event_changed(locked)
    meta = {"old_status": expected, "new_status": new_status}
    services._audit(locked, actor, action, locked, meta)
    services.notify_event_lifecycle(locked, new_status)
    return services._refresh(locked)


@transaction.atomic
def publish(event, *, actor):
    services = _boundary()
    locked = services._locked_event(event.pk)
    if locked.status != Event.Status.DRAFT:
        raise EventInvalidTransition("Only draft events can be published.")
    services._validate(locked)
    if locked.ends_at < timezone.now():
        raise EventInvalidTransition("Ended events cannot be published.")
    require_module_locked(locked.makerspace, "events")
    limits.check_quota(locked.makerspace, "events", adding=1)
    locked.status = Event.Status.PUBLISHED
    locked.save(update_fields=["status", "updated_at"])
    calendar_event_changed(locked)
    meta = {"old_status": Event.Status.DRAFT, "new_status": Event.Status.PUBLISHED}
    services._audit(locked, actor, "event.published", locked, meta)
    services.notify_event_lifecycle(locked, "published")
    return services._refresh(locked)


@transaction.atomic
def cancel(event, *, actor, notify=True):
    services = _boundary()
    locked = services._locked_event(event.pk)
    if locked.status != Event.Status.PUBLISHED:
        raise EventInvalidTransition(
            f"Cannot transition event from {locked.status} to {Event.Status.CANCELLED}."
        )
    survey = EventFeedbackSurvey.objects.select_for_update().filter(event=locked).first()
    certificates = list(EventAttendanceCertificate.objects.select_for_update().filter(
        registration__event=locked, status=EventAttendanceCertificate.Status.ACTIVE,
    ))
    now = timezone.now()
    if survey is not None and survey.is_open:
        survey.is_open = False
        survey.closed_at = now
        survey.save(update_fields=["is_open", "closed_at", "updated_at"])
        services._audit(
            locked, actor, "event.feedback_survey_closed", survey,
            {"reason": "event_cancelled"},
        )
    for certificate in certificates:
        certificate.status = EventAttendanceCertificate.Status.REVOKED
        certificate.revoked_at = now
        certificate.revoked_by = actor
        certificate.revocation_reason = (
            EventAttendanceCertificate.RevocationReason.EVENT_CANCELLED
        )
        certificate.save(update_fields=[
            "status", "revoked_at", "revoked_by", "revocation_reason",
        ])
        services._audit(
            locked, actor, "event.certificate_revoked", certificate,
            {"reason": certificate.revocation_reason, "revision": certificate.revision},
        )
    locked.status = Event.Status.CANCELLED
    locked.save(update_fields=["status", "updated_at"])
    calendar_event_changed(locked, now=now)
    services._audit(
        locked, actor, "event.cancelled", locked,
        {"old_status": Event.Status.PUBLISHED, "new_status": Event.Status.CANCELLED},
    )
    if notify:
        services.notify_event_lifecycle(locked, "cancelled")
    return services._refresh(locked)


@transaction.atomic
def complete(event, *, actor):
    return _transition(
        event, actor, Event.Status.PUBLISHED, Event.Status.COMPLETED, "event.completed"
    )
