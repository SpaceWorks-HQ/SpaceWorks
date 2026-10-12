"""A small versioned schema; no arbitrary JSON or client supplied reference fields."""

import math
import re
from django.core.exceptions import ValidationError
from apps.makerspaces.platform import feature_enabled


def validate_intake_schema(schema):
    if schema == {}:
        return
    if not isinstance(schema, dict) or set(schema) != {"version", "fields"} or type(schema["version"]) is not int or schema["version"] != 1:
        raise ValidationError("Intake schema requires version 1 and fields.")
    fields = schema["fields"]
    if not isinstance(fields, list) or not 1 <= len(fields) <= 20:
        raise ValidationError("Intake schema needs 1–20 fields.")
    seen = set()
    for field in fields:
        if not isinstance(field, dict) or set(field) - {"key", "label", "type", "required", "choices", "min", "max"}:
            raise ValidationError("Unsupported intake schema field.")
        key = field.get("key", "")
        if not isinstance(key, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,49}", key) or key.endswith("_id") or key in seen:
            raise ValidationError("Intake field keys must be unique names, without reference IDs.")
        seen.add(key)
        if not isinstance(field.get("label"), str) or not 1 <= len(field["label"]) <= 100:
            raise ValidationError("Intake field needs a label (up to 100 characters).")
        if field.get("type") not in ("text", "number", "integer", "choice", "boolean"):
            raise ValidationError("Unsupported intake field type.")
        if type(field.get("required", False)) is not bool:
            raise ValidationError("required must be boolean.")
        if field["type"] == "choice":
            choices = field.get("choices")
            if (not isinstance(choices, list) or not 1 <= len(choices) <= 100
                    or any(not isinstance(v, str) or not 1 <= len(v) <= 100 for v in choices)
                    or len(set(choices)) != len(choices)):
                raise ValidationError("Choice fields require unique text choices.")
        for bound in ("min", "max"):
            if bound in field and (type(field[bound]) not in (int, float) or abs(field[bound]) > 10**12 or not math.isfinite(field[bound])):
                raise ValidationError("Numeric bounds must be finite numbers.")
        if "min" in field and "max" in field and field["min"] > field["max"]:
            raise ValidationError("Minimum cannot exceed maximum.")


def validate_intake(space, machine_type, payload):
    schema = machine_type.intake_schema
    if not schema or not feature_enabled(space, "machines.structured_intake"):
        if payload:
            raise ValidationError("This machine type does not accept a capability payload.")
        return
    validate_intake_schema(schema)
    if not isinstance(payload, dict) or set(payload) - {"schema_version", "values"} or type(payload.get("schema_version")) is not int or payload.get("schema_version") != schema["version"]:
        raise ValidationError("Intake payload requires the current schema_version and values.")
    values = payload.get("values")
    if not isinstance(values, dict) or set(values) - {f["key"] for f in schema["fields"]}:
        raise ValidationError("Intake values contain unknown fields.")
    for field in schema["fields"]:
        key = field["key"]
        if key not in values:
            if field.get("required"):
                raise ValidationError(f"{key} is required.")
            continue
        value, kind = values[key], field["type"]
        valid = ((kind == "text" and isinstance(value, str) and len(value) <= 2000 and (bool(value.strip()) or not field.get("required")))
                 or (kind == "boolean" and type(value) is bool)
                 or (kind == "choice" and isinstance(value, str) and value in field["choices"])
                 or (kind in ("number", "integer") and type(value) in ((int,) if kind == "integer" else (int, float))
                     and abs(value) <= 10**12 and math.isfinite(value) and field.get("min", -float("inf")) <= value <= field.get("max", float("inf"))))
        if not valid:
            raise ValidationError(f"Invalid intake value for {key}.")
