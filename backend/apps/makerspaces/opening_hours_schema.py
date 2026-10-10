"""Shared OpenAPI shape for the public and staff opening-hours projections."""

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers


_TIME = {"type": "string", "pattern": r"^(?:[01][0-9]|2[0-3]):[0-5][0-9]$"}
_INTERVALS = {
    "type": "array", "maxItems": 24,
    "items": {"type": "object", "required": ["start", "end"],
              "additionalProperties": False,
              "properties": {"start": _TIME, "end": {
                  "type": "string", "pattern": r"^(?:(?:[01][0-9]|2[0-3]):[0-5][0-9]|24:00)$",
              }}},
}
_WEEK = {
    "type": "object", "additionalProperties": False,
    "required": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"],
    "properties": {day: _INTERVALS for day in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")},
}
_EMPTY = {"type": "object", "maxProperties": 0}


@extend_schema_field({
    "oneOf": [_EMPTY, {
        "type": "object", "required": ["weekly", "exceptions"], "additionalProperties": False,
        "properties": {
            "weekly": {"oneOf": [_EMPTY, _WEEK]},
            "exceptions": {"type": "object", "maxProperties": 366, "additionalProperties": _INTERVALS,
                           "description": "YYYY-MM-DD keys; each value replaces that date's weekly hours."},
        },
    }],
    "description": "Empty object means always open. Empty weekly hours mean always open except dated overrides. Empty interval lists mean closed. Sorted intervals use local wall time; split overnight hours across days.",
})
class OpeningHoursField(serializers.JSONField):
    pass
