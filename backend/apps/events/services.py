"""Audited mutation boundary for Events and their registrations."""

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.utils import timezone
from rest_framework import serializers

from apps.audit import services as audit
from apps.events.capacity import CONFIRMED_STATUSES
from apps.events.exceptions import (
    CapacityConflict,
    EventInvalidTransition,
)
from apps.events.models import Event, EventRegistration
from apps.events.notifications import notify_event_lifecycle
from apps.forms_schema.validation import validate_form_schema
from apps.makerspaces import limits
from apps.makerspaces.guards import require_module_locked
from apps.makerspaces.models import Makerspace

EVENT_FIELDS = frozenset(
    {'title', 'description', 'starts_at', 'ends_at', 'location',
     'location_kind', 'custom_form', 'capacity', 'is_public', 'payment_amount'}
)


def _locked_event(event_id):
    return Event.objects.select_for_update().select_related("makerspace").get(pk=event_id)


def _validate(instance):
    try:
        instance.full_clean(validate_unique=False, validate_constraints=False)
    except DjangoValidationError as exc:
        detail = exc.message_dict if hasattr(exc, "message_dict") else exc.messages
        raise serializers.ValidationError(detail) from exc
    if isinstance(instance, Event) and instance.ends_at < instance.starts_at:
        detail = {"ends_at": "End time must be at or after start time."}
        raise serializers.ValidationError(detail)


def _canonical_form(value):
    try:
        return validate_form_schema(value)
    except DjangoValidationError as exc:
        raise serializers.ValidationError({'custom_form': exc.messages}) from exc


def _audit(event, actor, action, target, meta=None):
    kwargs = {"makerspace": event.makerspace, "target": target, "meta": meta or {}}
    return audit.record(actor, action, **kwargs)


def _refresh(instance):
    instance.refresh_from_db()
    return instance


def _may_promote(event, now):
    return event.status == Event.Status.PUBLISHED and event.ends_at >= now


def _lock_waiters(event):
    return list(
        EventRegistration.objects.select_for_update().filter(
            event=event, status=EventRegistration.Status.WAITLISTED
        ).order_by("created_at", "id")
    )


def _promote(event, actor, waiters, count=None):
    selected = waiters if count is None else waiters[:count]
    for registration in selected:
        registration.event = event
        registration.status = EventRegistration.Status.REGISTERED
        registration.save(update_fields=["status"])
        from apps.events.service_payments import create_for_registered_registration

        create_for_registered_registration(registration, actor)
        meta = {"registration_id": registration.pk}
        _audit(event, actor, "event.registration_promoted", registration, meta)
        notify_event_lifecycle(event, "registration_promoted", registration.pk)
    return selected


@transaction.atomic
def create_event(
    *, makerspace, actor, title, description, starts_at, ends_at, location,
    capacity, is_public, location_kind=Event.LocationKind.OTHER, custom_form=None,
    payment_amount=0,
):
    locked_space = Makerspace.objects.select_for_update().get(pk=makerspace.pk)
    require_module_locked(locked_space, "events")
    event = Event(
        makerspace=locked_space,
        created_by=actor,
        title=title,
        description=description,
        starts_at=starts_at,
        ends_at=ends_at,
        location=location,
        location_kind=location_kind,
        custom_form=_canonical_form(custom_form),
        capacity=capacity,
        payment_amount=payment_amount,
        is_public=is_public,
    )
    _validate(event)
    event.save()
    _audit(event, actor, "event.created", event)
    return _refresh(event)


@transaction.atomic
def update_event(event, *, actor, **changes):
    locked = _locked_event(event.pk)
    if locked.status not in (Event.Status.DRAFT, Event.Status.PUBLISHED):
        raise EventInvalidTransition("Terminal events cannot be updated.")
    unknown = set(changes) - EVENT_FIELDS
    if unknown:
        raise serializers.ValidationError(
            {field: "This field cannot be updated." for field in sorted(unknown)}
        )

    if 'custom_form' in changes:
        changes['custom_form'] = _canonical_form(changes['custom_form'])

    now = timezone.now()
    old_capacity, old_ends_at = locked.capacity, locked.ends_at
    for field, value in changes.items():
        setattr(locked, field, value)
    _validate(locked)

    confirmed = EventRegistration.objects.filter(
        event=locked, status__in=CONFIRMED_STATUSES
    ).count()
    if locked.capacity > 0 and confirmed > locked.capacity:
        raise CapacityConflict("Capacity cannot be below confirmed occupancy.")
    if (
        locked.status == Event.Status.PUBLISHED
        and old_ends_at < now <= locked.ends_at
    ):
        limits.check_quota(locked.makerspace, "events", adding=1)

    promoted = []
    capacity_changed = "capacity" in changes and locked.capacity != old_capacity
    if (
        _may_promote(locked, now)
        and (locked.capacity == 0 or locked.capacity > confirmed)
    ):
        waiters = _lock_waiters(locked)
        if locked.capacity == 0:
            promoted = _promote(locked, actor, waiters)
        else:
            promoted = _promote(
                locked, actor, waiters, locked.capacity - confirmed
            )

    if changes:
        locked.save(update_fields=[*sorted(changes), "updated_at"])
    meta = {"changed_fields": sorted(changes)}
    if capacity_changed:
        meta.update(
            old_capacity=old_capacity,
            new_capacity=locked.capacity,
        )
    if capacity_changed or promoted:
        meta["promoted_registration_ids"] = [row.pk for row in promoted]
    _audit(locked, actor, "event.updated", locked, meta)
    return _refresh(locked)


def _transition(event, actor, expected, new_status, action):
    locked = _locked_event(event.pk)
    if locked.status != expected:
        message = f"Cannot transition event from {locked.status} to {new_status}."
        raise EventInvalidTransition(message)
    locked.status = new_status
    locked.save(update_fields=["status", "updated_at"])
    meta = {"old_status": expected, "new_status": new_status}
    _audit(locked, actor, action, locked, meta)
    notify_event_lifecycle(locked, new_status)
    return _refresh(locked)


@transaction.atomic
def publish(event, *, actor):
    locked = _locked_event(event.pk)
    if locked.status != Event.Status.DRAFT:
        raise EventInvalidTransition("Only draft events can be published.")
    _validate(locked)
    if locked.ends_at < timezone.now():
        raise EventInvalidTransition("Ended events cannot be published.")
    require_module_locked(locked.makerspace, "events")
    limits.check_quota(locked.makerspace, "events", adding=1)
    locked.status = Event.Status.PUBLISHED
    locked.save(update_fields=["status", "updated_at"])
    meta = {"old_status": Event.Status.DRAFT, "new_status": Event.Status.PUBLISHED}
    _audit(locked, actor, "event.published", locked, meta)
    notify_event_lifecycle(locked, "published")
    return _refresh(locked)


@transaction.atomic
def cancel(event, *, actor):
    return _transition(event, actor, Event.Status.PUBLISHED, Event.Status.CANCELLED, "event.cancelled")


@transaction.atomic
def complete(event, *, actor):
    return _transition(event, actor, Event.Status.PUBLISHED, Event.Status.COMPLETED, "event.completed")


@transaction.atomic
def cancel_registration(registration, *, actor=None):
    event = _locked_event(registration.event_id)
    locked = EventRegistration.objects.select_for_update().get(pk=registration.pk)
    if locked.event_id != event.pk or locked.status not in (
        EventRegistration.Status.REGISTERED,
        EventRegistration.Status.WAITLISTED,
    ):
        raise EventInvalidTransition("This registration cannot be cancelled.")
    old_status = locked.status
    locked.status = EventRegistration.Status.CANCELLED
    locked.save(update_fields=["status"])
    meta = {"registration_id": locked.pk, "old_status": old_status}
    _audit(event, actor, "event.registration_cancelled", locked, meta)
    notify_event_lifecycle(event, "registration_cancelled", locked.pk)
    from apps.events.service_payments import cancel_for_registration

    cancel_for_registration(locked, actor)
    if (
        old_status == EventRegistration.Status.REGISTERED
        and event.capacity > 0
        and _may_promote(event, timezone.now())
    ):
        waiters = _lock_waiters(event)
        if waiters:
            _promote(event, actor, waiters, 1)
    return _refresh(locked)


@transaction.atomic
def mark_attended(registration, *, actor):
    event = _locked_event(registration.event_id)
    locked = EventRegistration.objects.select_for_update().get(pk=registration.pk)
    if (
        locked.event_id != event.pk
        or locked.status != EventRegistration.Status.REGISTERED
        or event.status not in (Event.Status.PUBLISHED, Event.Status.COMPLETED)
    ):
        raise EventInvalidTransition("This registration cannot be marked attended.")
    locked.status = EventRegistration.Status.ATTENDED
    locked.save(update_fields=["status"])
    _audit(
        event, actor, "event.registration_attended", locked,
        {"registration_id": locked.pk},
    )
    notify_event_lifecycle(event, "registration_attended", locked.pk)
    return _refresh(locked)


from apps.events.services_registration import register  # noqa: E402
