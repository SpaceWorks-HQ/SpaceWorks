"""Typed, relation-free provenance carried across deployment boundaries."""

from django.core.exceptions import ValidationError
from django.utils.dateparse import parse_datetime


ACTOR_SNAPSHOT_FIELDS = frozenset(
    {"actor_username", "actor_display", "source_user_id", "recorded_at"}
)


def validate_actor_snapshot(value):
    """Require the complete text snapshot used for an imported source actor."""
    if not isinstance(value, dict) or set(value) != ACTOR_SNAPSHOT_FIELDS:
        raise ValidationError(
            "Actor provenance must contain username, display, source id, and time."
        )
    if not all(isinstance(value[field], str) for field in ACTOR_SNAPSHOT_FIELDS):
        raise ValidationError("Every actor provenance value must be text.")
    if not value["source_user_id"] or parse_datetime(value["recorded_at"]) is None:
        raise ValidationError("Actor provenance needs a source id and ISO timestamp.")


def normalized_actor_snapshot(value):
    """Validate and copy a snapshot before it crosses into live membership state."""
    if value is None:
        return None
    validate_actor_snapshot(value)
    return {field: value[field] for field in sorted(ACTOR_SNAPSHOT_FIELDS)}
