from uuid import uuid4

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied

from apps.events.exceptions import DuplicateCheckInOperation, EventInvalidTransition
from apps.events.models import (
    Event,
    EventCheckInEvent,
    EventCheckInStationCredential,
    EventRegistration,
)
from apps.makerspaces.guards import require_feature_locked


FEATURE_SOURCES = {
    EventCheckInEvent.Source.OFFLINE_SYNC,
    EventCheckInEvent.Source.VENUE_STATION,
}


def _boundary():
    from apps.events import services

    return services


def _lock_registration(event, registration_id):
    registration = EventRegistration.objects.select_for_update().get(pk=registration_id)
    if registration.event_id != event.pk:
        raise EventInvalidTransition("Registration does not belong to this event.")
    registration.event = event
    return registration


@transaction.atomic
def mark_attended_with_event(
    registration,
    *,
    actor,
    source=EventCheckInEvent.Source.ONLINE,
    operation_id=None,
    attended_at=None,
    session_id=None,
    station_version=None,
):
    services = _boundary()
    event = services._locked_event(registration.event_id)
    if source in FEATURE_SOURCES:
        event.makerspace = require_feature_locked(
            event.makerspace_id, "events.offline_checkin"
        )
    if source == EventCheckInEvent.Source.VENUE_STATION:
        credential = (
            EventCheckInStationCredential.objects.select_for_update()
            .filter(
                event=event,
                is_enabled=True,
                version=station_version,
            )
            .only("pk")
            .first()
        )
        if credential is None:
            raise PermissionDenied("Invalid station session.")
    operation_id = operation_id or uuid4()
    if EventCheckInEvent.objects.filter(
        makerspace_id=event.makerspace_id,
        operation_id=operation_id,
    ).exists():
        raise DuplicateCheckInOperation()
    locked = _lock_registration(event, registration.pk)
    if (
        locked.status != EventRegistration.Status.REGISTERED
        or event.status not in (Event.Status.PUBLISHED, Event.Status.COMPLETED)
    ):
        raise EventInvalidTransition("This registration cannot be marked attended.")

    occurred_at = attended_at or timezone.now()
    check_in = EventCheckInEvent(
        makerspace=event.makerspace,
        event=event,
        registration=locked,
        operation_id=operation_id,
        source=source,
        attended_at=occurred_at,
        actor=actor,
        session_id=session_id,
        station_version=station_version,
    )
    # The operation UUID is deployment-global, but validation must not query another
    # tenant to explain a collision. The database enforces uniqueness; the service maps
    # that race to the uniform idempotent outcome.
    check_in.full_clean(validate_unique=False)
    check_in.save()
    locked.status = EventRegistration.Status.ATTENDED
    locked.save(update_fields=["status"])
    services._audit(
        event,
        actor,
        "event.registration_attended",
        locked,
        {
            "registration_id": locked.pk,
            "check_in_event_id": check_in.pk,
            "source": source,
            "operation_id": str(operation_id),
            "reported_occurred_at": occurred_at.isoformat(),
            "recorded_at": check_in.recorded_at.isoformat(),
            "session_id": str(session_id) if session_id else None,
            "station_version": station_version,
        },
    )
    services.notify_event_lifecycle(event, "registration_attended", locked.pk)
    return services._refresh(locked), check_in


def mark_attended(registration, **kwargs):
    updated, _check_in = mark_attended_with_event(registration, **kwargs)
    return updated
