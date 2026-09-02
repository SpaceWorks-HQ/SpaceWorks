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
from apps.events.models import (
    Event,
    EventRegistration,
)
from apps.events.notifications import notify_event_lifecycle
from apps.forms_schema.validation import validate_form_schema
from apps.makerspaces import limits
from apps.makerspaces.guards import require_module_locked
from apps.makerspaces.models import Makerspace

EVENT_FIELDS = frozenset(
    {'title', 'description', 'starts_at', 'ends_at', 'location',
     'location_kind', 'custom_form', 'capacity', 'is_public', 'payment_amount',
     'registration_requires_approval', 'registration_cutoff_at',
     'registration_cutoff_lead_minutes', 'timezone_name'}
)
INHERITABLE_FIELDS = EVENT_FIELDS | {"image_key"}


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


@transaction.atomic
def create_event(
    *, makerspace, actor, title, description, starts_at, ends_at, location,
    capacity, is_public, location_kind=Event.LocationKind.OTHER, custom_form=None,
    payment_amount=0, registration_requires_approval=False,
    registration_cutoff_at=None, registration_cutoff_lead_minutes=None,
    timezone_name=None,
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
        registration_requires_approval=registration_requires_approval,
        registration_cutoff_at=registration_cutoff_at,
        registration_cutoff_lead_minutes=registration_cutoff_lead_minutes,
        is_public=is_public,
        **({"timezone_name": timezone_name} if timezone_name else {}),
    )
    _validate(event)
    event.save()
    _audit(event, actor, "event.created", event)
    return _refresh(event)


@transaction.atomic
def update_event(event, *, actor, inherit_fields=(), **changes):
    from apps.events.services_calendar import CALENDAR_EVENT_FIELDS, calendar_event_changed

    locked = _locked_event(event.pk)
    if locked.status not in (Event.Status.DRAFT, Event.Status.PUBLISHED):
        raise EventInvalidTransition("Terminal events cannot be updated.")
    unknown = set(changes) - EVENT_FIELDS
    if unknown:
        raise serializers.ValidationError(
            {field: "This field cannot be updated." for field in sorted(unknown)}
        )
    inherit_fields = set(inherit_fields or ())
    invalid_inherit = inherit_fields - INHERITABLE_FIELDS
    if invalid_inherit:
        raise serializers.ValidationError(
            {field: "This field cannot inherit from a series." for field in invalid_inherit}
        )
    if inherit_fields & set(changes):
        raise serializers.ValidationError(
            {field: "A field cannot be changed and inherited together." for field in inherit_fields & set(changes)}
        )
    if inherit_fields and locked.series_id is None:
        raise serializers.ValidationError({"inherit_fields": "This event is not in a series."})
    if inherit_fields:
        from apps.events.services_series import occurrence_inherited_value

        for field in inherit_fields:
            changes[field] = occurrence_inherited_value(locked, field)

    if 'custom_form' in changes:
        changes['custom_form'] = _canonical_form(changes['custom_form'])
    if (
        "registration_requires_approval" in changes
        and changes["registration_requires_approval"]
        != locked.registration_requires_approval
        and locked.status != Event.Status.DRAFT
    ):
        raise EventInvalidTransition(
            "Approval policy can only be changed while the event is a draft."
        )

    now = timezone.now()
    old_capacity, old_ends_at, old_image_key = locked.capacity, locked.ends_at, locked.image_key
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
        if not locked.registration_requires_approval:
            promoted = promote_automatically(
                locked,
                actor,
                None if locked.capacity == 0 else locked.capacity - confirmed,
            )

    if changes:
        update_fields = set(changes)
        if locked.series_id:
            overrides = set(locked.series_override_fields or [])
            overrides.update(set(changes) - inherit_fields)
            overrides.difference_update(inherit_fields)
            locked.series_override_fields = sorted(overrides)
            update_fields.add("series_override_fields")
        locked.save(update_fields=[*sorted(update_fields), "updated_at"])
        if set(changes) & CALENDAR_EVENT_FIELDS:
            calendar_event_changed(locked)
        if "image_key" in inherit_fields and old_image_key:
            from apps.inventory import public_image_storage

            public_image_storage.release_public_image_on_commit(
                locked.makerspace, old_image_key
            )
    meta = {"changed_fields": sorted(changes)}
    if inherit_fields:
        meta["inherited_fields"] = sorted(inherit_fields)
    if capacity_changed:
        meta.update(
            old_capacity=old_capacity,
            new_capacity=locked.capacity,
        )
    if capacity_changed or promoted:
        meta["promoted_registration_ids"] = [row.pk for row in promoted]
    _audit(locked, actor, "event.updated", locked, meta)
    return _refresh(locked)


from apps.events.services_registration import register  # noqa: E402
from apps.events.services_registration_state import (  # noqa: E402
    approve_registration,
    cancel_registration,
    correct_attendance,
    mark_attended,
    promote_automatically,
    promote_registration,
    reject_registration,
)
from apps.events.services_lifecycle import cancel, complete, publish  # noqa: E402
