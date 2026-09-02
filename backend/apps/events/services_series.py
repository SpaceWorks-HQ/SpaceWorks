from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from datetime import datetime, timedelta, timezone as dt_timezone
from zoneinfo import ZoneInfo

from django.utils import timezone
from rest_framework import serializers

from apps.audit import services as audit
from apps.events import services
from apps.events.exceptions import EventInvalidTransition
from apps.events.models import (
    Event,
    EventCollaborator,
    EventOrganizer,
    EventSeries,
)
from apps.events.services_recurrence import (
    occurrences,
    validate_series_recurrence,
)
from apps.events.services_calendar import (
    CALENDAR_SERIES_FIELDS,
    calendar_event_changed,
    calendar_series_changed,
)
from apps.forms_schema.validation import validate_form_schema
from apps.makerspaces import limits
from apps.makerspaces.guards import require_module_locked
from apps.makerspaces.models import Makerspace


TEMPLATE_FIELDS = frozenset({
    "title", "description", "location", "location_kind", "custom_form", "capacity",
    "payment_amount", "registration_requires_approval",
    "registration_cutoff_lead_minutes", "is_public",
})
RECURRENCE_FIELDS = frozenset({
    "recurrence_timezone", "dtstart_local_date", "dtstart_local_time",
    "recurrence_rule", "duration_minutes",
})
SERIES_FIELDS = TEMPLATE_FIELDS | RECURRENCE_FIELDS


def occurrence_inherited_value(event, field):
    series = event.series
    if field == "starts_at":
        local_text = event.series_occurrence_key.split(":", 1)[1]
        local = datetime.strptime(local_text, "%Y%m%dT%H%M%S").replace(
            tzinfo=ZoneInfo(series.recurrence_timezone), fold=0
        )
        return local.astimezone(dt_timezone.utc)
    if field == "ends_at":
        start = occurrence_inherited_value(event, "starts_at")
        return start + timedelta(minutes=series.duration_minutes)
    if field == "registration_cutoff_at":
        return None
    if field == "timezone_name":
        return series.recurrence_timezone
    if field == "image_key":
        return ""
    return getattr(series, field)


def _validate(series):
    if "custom_form" in series.__dict__:
        try:
            series.custom_form = validate_form_schema(series.custom_form)
        except DjangoValidationError as exc:
            raise serializers.ValidationError({"custom_form": exc.messages}) from exc
    series.recurrence_rule = validate_series_recurrence(series)
    try:
        series.full_clean(validate_unique=False, validate_constraints=False)
    except DjangoValidationError as exc:
        detail = exc.message_dict if hasattr(exc, "message_dict") else exc.messages
        raise serializers.ValidationError(detail) from exc


def _event_values(series, occurrence):
    return {
        "makerspace": series.makerspace,
        "series": series,
        "series_occurrence_key": occurrence.key,
        "series_revision": series.revision,
        "title": series.title,
        "description": series.description,
        "starts_at": occurrence.starts_at,
        "ends_at": occurrence.ends_at,
        "location": series.location,
        "location_kind": series.location_kind,
        "custom_form": series.custom_form,
        "capacity": series.capacity,
        "payment_amount": series.payment_amount,
        "registration_requires_approval": series.registration_requires_approval,
        "registration_cutoff_lead_minutes": series.registration_cutoff_lead_minutes,
        "is_public": series.is_public,
        "status": (
            Event.Status.PUBLISHED
            if series.status == EventSeries.Status.PUBLISHED
            else Event.Status.DRAFT
        ),
        "timezone_name": series.recurrence_timezone,
        "created_by": series.created_by,
    }


def _project_authority(series, event):
    for source in series.collaborators.filter(status="accepted"):
        EventCollaborator.objects.get_or_create(
            event=event,
            makerspace=source.makerspace,
            defaults={
                "status": EventCollaborator.Status.ACCEPTED,
                "invited_by": source.invited_by,
                "responded_by": source.responded_by,
                "responded_at": source.responded_at,
                "source_series_collaboration": source,
            },
        )
    for source in series.organizers.all():
        EventOrganizer.objects.get_or_create(
            event=event,
            organization=source.organization,
            defaults={"created_by": source.created_by, "source_series_organizer": source},
        )


def _materialize_locked(series, *, actor, now):
    generated = occurrences(series, now=now)
    existing = set(
        Event.objects.filter(series=series).values_list("series_occurrence_key", flat=True)
    )
    pending = [item for item in generated if item.key not in existing]
    if series.status == EventSeries.Status.PUBLISHED and pending:
        limits.check_quota(series.makerspace, "events", adding=len(pending))
    created = []
    for item in pending:
        event = Event.objects.create(**_event_values(series, item))
        _project_authority(series, event)
        audit.record(
            actor, "event.series_occurrence_created", makerspace=series.makerspace,
            target=event, meta={"series_id": series.pk, "occurrence_key": item.key},
        )
        created.append(event)
    series.last_materialized_at = now
    series.last_generation_error_code = ""
    series.save(update_fields=(
        "recurrence_rule", "last_materialized_at", "last_generation_error_code", "updated_at"
    ))
    return created


@transaction.atomic
def create_series(*, makerspace, actor, **values):
    locked_space = Makerspace.objects.select_for_update().get(pk=makerspace.pk)
    require_module_locked(locked_space, "events")
    unknown = set(values) - SERIES_FIELDS
    if unknown:
        raise serializers.ValidationError({field: "Unknown field." for field in unknown})
    series = EventSeries(makerspace=locked_space, created_by=actor, **values)
    _validate(series)
    series.save()
    created = _materialize_locked(series, actor=actor, now=timezone.now())
    audit.record(
        actor, "event.series_created", makerspace=locked_space, target=series,
        meta={"occurrence_ids": [event.pk for event in created]},
    )
    return series, created


@transaction.atomic
def extend_series(series, *, actor=None):
    locked = EventSeries.objects.select_for_update().get(pk=series.pk)
    if locked.status in (EventSeries.Status.CANCELLED, EventSeries.Status.COMPLETED):
        raise EventInvalidTransition("Terminal series cannot be extended.")
    require_module_locked(locked.makerspace_id, "events")
    created = _materialize_locked(locked, actor=actor, now=timezone.now())
    audit.record(
        actor, "event.series_extended", makerspace=locked.makerspace, target=locked,
        meta={"created_ids": [event.pk for event in created]},
    )
    return locked, created


def _apply_template(series, event, changed_fields):
    overrides = set(event.series_override_fields or [])
    applied = []
    for field in changed_fields & TEMPLATE_FIELDS:
        if field not in overrides:
            setattr(event, field, getattr(series, field))
            applied.append(field)
    if applied:
        event.save(update_fields=(*sorted(applied), "updated_at"))
        if set(applied) & {"title", "description", "location", "is_public"}:
            calendar_event_changed(event)


@transaction.atomic
def update_series(series, *, actor, effective_from=None, **changes):
    locked = EventSeries.objects.select_for_update().get(pk=series.pk)
    if locked.status not in (EventSeries.Status.DRAFT, EventSeries.Status.PUBLISHED):
        raise EventInvalidTransition("Terminal series cannot be updated.")
    unknown = set(changes) - SERIES_FIELDS
    if unknown:
        raise serializers.ValidationError({field: "This field cannot be updated." for field in unknown})
    recurrence_changed = bool(set(changes) & RECURRENCE_FIELDS)
    if recurrence_changed and locked.status == EventSeries.Status.PUBLISHED and effective_from is None:
        raise serializers.ValidationError({"effective_from": "Required for a published schedule change."})
    cutoff = effective_from or timezone.now()
    old_revision = locked.revision
    for field, value in changes.items():
        setattr(locked, field, value)
    if recurrence_changed:
        locked.revision += 1
    _validate(locked)
    locked.save(update_fields=(*sorted(changes), "revision", "updated_at"))
    if set(changes) & CALENDAR_SERIES_FIELDS:
        calendar_series_changed(locked)

    future = list(Event.objects.select_for_update().filter(
        series=locked, starts_at__gte=cutoff,
        status__in=(Event.Status.DRAFT, Event.Status.PUBLISHED),
    ).order_by("pk"))
    require_module_locked(locked.makerspace_id, "events")
    removed = []
    if recurrence_changed:
        for event in future:
            if event.status == Event.Status.PUBLISHED:
                services.cancel(event, actor=actor, notify=False)
            else:
                event_id = event.pk
                event.delete()
                removed.append(event_id)
                audit.record(
                    actor, "event.series_occurrence_removed", makerspace=locked.makerspace,
                    target=locked, meta={"event_id": event_id, "old_revision": old_revision},
                )
    else:
        for event in future:
            _apply_template(locked, event, set(changes))
    created = _materialize_locked(locked, actor=actor, now=timezone.now())
    audit.record(
        actor, "event.series_updated", makerspace=locked.makerspace, target=locked,
        meta={
            "changed_fields": sorted(changes), "old_revision": old_revision,
            "new_revision": locked.revision, "removed_ids": removed,
            "created_ids": [event.pk for event in created],
        },
    )
    return locked, created, removed


from apps.events.services_series_lifecycle import (  # noqa: E402
    cancel_series,
    complete_series,
    publish_series,
)
