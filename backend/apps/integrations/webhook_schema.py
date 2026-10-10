"""Webhook v2: identifiers and event time, independent of editable chat wording."""

from apps.integrations.lifecycle_data import lifecycle_data
from apps.integrations.notification_catalog import FEATURE_EVENTS

FAMILY_IDS = {
    "hardware_requests": ("request_id", "payment_id"),
    "printing": ("machine_service_request_id", "request_id", "machine_id"),
    "events": ("event_id", "series_id", "registration_id"),
    "bookings": ("booking_id", "space_id"),
    "maintenance": ("machine_id", "schedule_id", "maintenance_log_id"),
    "members": ("membership_request_id", "membership_id"),
    "api_access": ("api_key_request_id",),
    "devices": (),
    "payments": ("payment_id", "refund_id", "request_id", "booking_id", "registration_id", "membership_id"),
    "stock": ("to_buy_item_id", "pool_id"),
    "certifications": ("certification_grant_id", "certification_type_id", "membership_id"),
    "reports": ("schedule_id",),
}


def canonical_event(log):
    if log.event == "delivery_test":
        return "system.delivery_test"
    return f"{log.feature}.{log.event}"


def structured_body(log):
    ids = lifecycle_data(log.payload or {})
    permitted = FAMILY_IDS.get(log.feature, ())
    return {
        "version": 2, "id": str(log.pk), "event": canonical_event(log),
        "makerspace_id": log.makerspace_id,
        "occurred_at": (log.payload or {}).get("occurred_at") or log.created_at.isoformat(),
        "data": {key: value for key, value in ids.items() if key in permitted},
    }


def schema_catalog():
    events = {f"{family}.{event}": FAMILY_IDS[family]
              for family, values in FEATURE_EVENTS.items() for event in values}
    events["system.delivery_test"] = ()
    # Scheduled reports also reuse signed destinations, but carry no domain identifier here.
    events["reports.scheduled_report"] = FAMILY_IDS["reports"]
    definitions = {}
    for name, ids in sorted(events.items()):
        definitions[name] = {
            "type": "object", "additionalProperties": False,
            "required": ["version", "id", "event", "makerspace_id", "occurred_at", "data"],
            "properties": {
                "version": {"const": 2}, "id": {"type": "string", "minLength": 1},
                "event": {"const": name}, "makerspace_id": {"type": "integer", "minimum": 1},
                "occurred_at": {"type": "string", "format": "date-time"},
                "data": {"type": "object", "additionalProperties": False,
                         "properties": {key: {"type": "integer", "minimum": 1} for key in ids}},
            },
        }
    return {"$schema": "https://json-schema.org/draft/2020-12/schema",
            "title": "SpaceWorks webhook v2 event catalogue", "$defs": definitions,
            "oneOf": [{"$ref": f"#/$defs/{name}"} for name in definitions]}
