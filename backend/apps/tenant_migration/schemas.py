"""Closed JSON schemas for cross-tenant reference snapshots."""

from datetime import datetime

from django.core.exceptions import ValidationError

STRING = "string"
INTEGER = "integer"
BOOLEAN = "boolean"
TIMESTAMP = "timestamp"


def object_schema(**fields):
    return {"type": "object", "fields": fields, "required": frozenset(fields)}


MAKERSPACE = object_schema(name=STRING, slug=STRING)
EVENT = object_schema(title=STRING, starts_at=TIMESTAMP, ends_at=TIMESTAMP)
CONTAINER = object_schema(label=STRING, makerspace=MAKERSPACE)

EDGE_SCHEMAS = {
    ("events.EventCollaborator", "event"): EVENT,
    ("events.EventRegistration", "registered_via_makerspace"): MAKERSPACE,
    ("events.EventRegistration", "payment_via_makerspace"): MAKERSPACE,
    ("operations.StockTransfer", "source_container"): CONTAINER,
    ("operations.StockTransfer", "destination_container"): CONTAINER,
    ("operations.StockTransfer", "source_makerspace"): MAKERSPACE,
    ("operations.StockTransfer", "destination_makerspace"): MAKERSPACE,
    ("payments.Payment", "via_makerspace"): MAKERSPACE,
}


def validate_snapshot(source_model_label, field_name, snapshot):
    """Reject snapshots that do not exactly match their declared edge schema."""
    edge = (source_model_label, field_name)
    schema = EDGE_SCHEMAS.get(edge)
    if schema is None:
        raise ValidationError({"snapshot": f"Unknown external reference edge: {edge!r}."})
    _validate_value(snapshot, schema, path="snapshot")


def _validate_value(value, schema, *, path):
    if isinstance(schema, dict):
        if not isinstance(value, dict):
            raise ValidationError({"snapshot": f"{path} must be an object."})
        fields = schema["fields"]
        missing = schema["required"] - value.keys()
        if missing:
            raise ValidationError(
                {"snapshot": f"{path} is missing required keys: {', '.join(sorted(missing))}."}
            )
        extra = value.keys() - fields.keys()
        if extra:
            raise ValidationError(
                {"snapshot": f"{path} has unknown keys: {', '.join(sorted(extra))}."}
            )
        for key, field_schema in fields.items():
            _validate_value(value[key], field_schema, path=f"{path}.{key}")
        return

    valid = {
        STRING: lambda item: isinstance(item, str),
        INTEGER: lambda item: isinstance(item, int) and not isinstance(item, bool),
        BOOLEAN: lambda item: isinstance(item, bool),
        TIMESTAMP: _is_timestamp,
    }[schema](value)
    if not valid:
        raise ValidationError({"snapshot": f"{path} must be a {schema}."})


def _is_timestamp(value):
    if not isinstance(value, str):
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True
