from dataclasses import dataclass
import hashlib
import json
from zoneinfo import ZoneInfo

from django.db import transaction
from django.utils import timezone
from rest_framework import serializers

from apps.audit import services as audit
from apps.events.badge_templates import (
    MAX_BADGES,
    MAX_PAGES,
    MAX_TEXT_LENGTH,
    normalize_badge_template,
    page_layout,
)
from apps.events.exceptions import EventInvalidTransition
from apps.events.models import Event, EventRegistration
from apps.makerspaces.guards import require_module_locked


@dataclass(frozen=True)
class BadgeSnapshot:
    registration_id: int
    checkin_token: str
    fields: tuple[tuple[str, str], ...]


def _answer_values(registration):
    snapshot = registration.custom_answers or {}
    answers = snapshot.get("answers", []) if isinstance(snapshot, dict) else []
    return {
        str(answer.get("id")): answer.get("value")
        for answer in answers
        if isinstance(answer, dict) and answer.get("id") is not None
    }


def _text(value):
    if isinstance(value, list):
        value = ", ".join(str(item) for item in value)
    elif isinstance(value, bool):
        value = "Yes" if value else "No"
    elif value is None:
        value = ""
    value = str(value)
    if len(value) > MAX_TEXT_LENGTH:
        raise serializers.ValidationError(
            {"fields": f"Selected badge text exceeds {MAX_TEXT_LENGTH} characters."}
        )
    return value


def _field_values(event, registration, selectors):
    labels = {str(row["id"]): row["label"] for row in (event.custom_form or [])}
    answers = _answer_values(registration)
    date_time = timezone.localtime(event.starts_at, timezone=ZoneInfo(event.timezone_name))
    values = {
        "name": ("Name", registration.name),
        "event_title": ("Event", event.title),
        "date_time": ("When", date_time.strftime("%d %b %Y, %H:%M")),
        "location": ("Location", event.location),
        "registration_number": ("Registration", str(registration.pk)),
        "email": ("Email", registration.email),
        "phone": ("Phone", registration.phone),
    }
    output = []
    for selector in selectors:
        if selector.startswith("custom:"):
            key = selector[7:]
            output.append((labels[key], _text(answers.get(key, ""))))
        else:
            label, value = values[selector]
            output.append((label, _text(value)))
    return tuple(output)


@transaction.atomic
def save_badge_template(event, template, *, actor):
    locked = Event.objects.select_for_update().get(pk=event.pk)
    require_module_locked(locked.makerspace_id, "events")
    if locked.status == Event.Status.CANCELLED:
        raise EventInvalidTransition("Cancelled events cannot change badge templates.")
    normalized = normalize_badge_template(template, locked)
    locked.badge_template = normalized
    locked.save(update_fields=("badge_template", "updated_at"))
    audit.record(
        actor, "event.badge_template_updated", makerspace=locked.makerspace,
        target=locked, meta={"version": normalized["version"], "fields": normalized["fields"]},
    )
    return normalized


@transaction.atomic
def prepare_badges(event, registration_ids, *, actor, template_override=None,
                   include_attended=False):
    if not registration_ids or len(registration_ids) > MAX_BADGES:
        raise serializers.ValidationError(
            {"registration_ids": f"Choose between 1 and {MAX_BADGES} registrations."}
        )
    if len(registration_ids) != len(set(registration_ids)):
        raise serializers.ValidationError({"registration_ids": "Duplicate IDs are not allowed."})
    locked = Event.objects.select_for_update().get(pk=event.pk)
    require_module_locked(locked.makerspace_id, "events")
    if locked.status not in (Event.Status.PUBLISHED, Event.Status.COMPLETED):
        raise EventInvalidTransition("Badges require a published or completed event.")
    normalized = normalize_badge_template(
        template_override if template_override is not None else locked.badge_template,
        locked,
    )
    _width, _height, columns, rows = page_layout(normalized)
    pages = (len(registration_ids) + columns * rows - 1) // (columns * rows)
    if pages > MAX_PAGES:
        raise serializers.ValidationError({"registration_ids": "The badge PDF is too large."})
    registrations = list(EventRegistration.objects.select_for_update().filter(
        event=locked, pk__in=registration_ids,
    ).order_by("pk"))
    if len(registrations) != len(registration_ids):
        raise EventRegistration.DoesNotExist
    allowed = {EventRegistration.Status.REGISTERED}
    if include_attended:
        allowed.add(EventRegistration.Status.ATTENDED)
    if any(registration.status not in allowed for registration in registrations):
        raise EventInvalidTransition("A selected registration is not eligible for a badge.")
    snapshots = tuple(BadgeSnapshot(
        registration_id=registration.pk,
        checkin_token=str(registration.checkin_token),
        fields=_field_values(locked, registration, normalized["fields"]),
    ) for registration in registrations)
    selected_digest = hashlib.sha256(json.dumps(
        sorted(registration_ids), separators=(",", ":")
    ).encode()).hexdigest()
    audit.record(
        actor, "event.badges_generated", makerspace=locked.makerspace, target=locked,
        meta={
            "count": len(snapshots), "fields": normalized["fields"],
            "template_version": normalized["version"], "selected_ids_sha256": selected_digest,
        },
    )
    return normalized, snapshots
