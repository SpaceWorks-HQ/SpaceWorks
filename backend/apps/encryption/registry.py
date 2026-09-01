"""Fixed, query-free allowlist for the narrow scoped-PII boundary."""

from dataclasses import dataclass


@dataclass(frozen=True)
class PiiField:
    model_label: str
    field_name: str
    makerspace_path: str | None
    max_length: int | None
    classification: str
    index_kind: str


def _fields(label, names, path, classification, indexes):
    return tuple(
        PiiField(label, name, path, limit, classification, index)
        for name, limit, index in zip(names, indexes[0], indexes[1], strict=True)
    )


SOURCE_FIELDS = (
    *_fields("hardware_requests.HardwareRequest", ("requester_username", "requester_name", "requester_contact_email", "requester_contact_phone"), "makerspace_id", "source", ((150, 200, 254, 32), ("none", "bloom", "bloom_exact", "none"))),
    *_fields("events.EventRegistration", ("name", "email", "phone"), "event.makerspace_id", "source", ((200, 254, 32), ("none", "event_exact", "none"))),
    *_fields("events.EventFeedbackResponse", ("answers_snapshot",), "survey.event.makerspace_id", "source", ((None,), ("none",))),
    *_fields("events.EventAttendanceCertificate", ("recipient_name",), "registration.event.makerspace_id", "source", ((None,), ("none",))),
    *_fields("bookings.Booking", ("name", "email", "phone", "note"), "space.makerspace_id", "source", ((200, 254, 32, None), ("none", "none", "none", "none"))),
    *_fields("machines.MachineServiceRequest", ("requester_name", "contact_email", "contact_phone"), "makerspace_id", "source", ((None, None, None), ("bloom", "bloom_exact", "none"))),
    *_fields("machines.MachineUsageEntry", ("requester_name", "contact_email", "contact_phone", "note"), "machine.makerspace_id", "source", ((120, 254, 40, None), ("bloom", "bloom_exact", "none", "none"))),
)

SECONDARY_FIELDS = _fields(
    "integrations.EmailLog", ("to_email", "subject", "text_body", "html_body"),
    "makerspace_id", "secondary", ((255, 255, None, None), ("none",) * 4),
)
ALL_FIELDS = SOURCE_FIELDS + SECONDARY_FIELDS
BY_MODEL = {}
for _field in ALL_FIELDS:
    BY_MODEL.setdefault(_field.model_label, []).append(_field)
BY_MODEL = {label: tuple(fields) for label, fields in BY_MODEL.items()}


def fields_for_label(model_label):
    """Accessor for callers holding a label rather than a model.

    Call this instead of importing ``BY_MODEL``. A module-level ``from ... import
    BY_MODEL`` binds whatever the map contained at import time, which stops being
    the truth the moment registration becomes per-app (plan B2).
    """
    return BY_MODEL.get(model_label, ())


def all_fields():
    """Accessor for the full field list; see ``fields_for_label`` for why."""
    return ALL_FIELDS


def registered_labels():
    """Accessor for every mapped model label; see ``fields_for_label`` for why."""
    return tuple(BY_MODEL)


def fields_for(model_or_instance):
    meta = model_or_instance._meta
    return BY_MODEL.get(meta.label, ())


def field_for(model_or_instance, name):
    return next((item for item in fields_for(model_or_instance) if item.field_name == name), None)


def makerspace_id_for(instance, field):
    """Resolve only the registry-declared tenant relationship, never a fallback."""
    if field.makerspace_path == "makerspace_id":
        return instance.makerspace_id
    current = instance
    for component in field.makerspace_path.split("."):
        current = getattr(current, component)
    return current
