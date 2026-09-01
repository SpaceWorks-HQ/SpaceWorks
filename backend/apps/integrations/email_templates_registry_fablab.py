"""Registry entries for the events/bookings/maintenance/membership email streams.

This is an EXTENSION of `email_templates_registry`, not a second templating system: the
same `EmailTemplateRegistryEntry`, the same declared `fields` list the editor renders, the
same `sample_context` the validator renders against, and the same Django `Template`. What
changes is coverage — the registry previously stopped at hardware and printing, so the
four FabLab streams had their wording hard-coded in each adapter with no way for a
makerspace to edit it.

The four streams are keyed by the value the adapters already pass as `EmailDelivery.stream`
(`membership`, not `members` — the feature key and the stream name genuinely differ here,
and existing `EmailLog` rows carry the stream, so renaming it would orphan them).
"""

from datetime import datetime, timezone

from apps.integrations.email_templates_registry_fablab_defaults import (
    BOOKINGS_REQUESTER_BODIES,
    BOOKINGS_REQUESTER_SUBJECT,
    BOOKINGS_REQUESTER_TEXT,
    BOOKINGS_STAFF_SUBJECT,
    BOOKINGS_STAFF_TEXT,
    EVENTS_REQUESTER_BODIES,
    EVENTS_REQUESTER_SUBJECTS,
    EVENTS_REQUESTER_TEXT,
    EVENTS_STAFF_SUBJECT,
    EVENTS_STAFF_TEXT,
    MAINTENANCE_REQUESTER_BODIES,
    MAINTENANCE_REQUESTER_SUBJECTS,
    MAINTENANCE_REQUESTER_TEXT,
    MAINTENANCE_STAFF_SUBJECT,
    MAINTENANCE_STAFF_TEXT,
    MEMBERSHIP_REQUESTER_SUBJECTS,
    MEMBERSHIP_REQUESTER_TEXTS,
    MEMBERSHIP_STAFF_SUBJECTS,
    MEMBERSHIP_STAFF_TEXTS,
)

EVENTS_KEYS = (
    "published",
    "cancelled",
    "completed",
    "registration_created",
    "registration_cancelled",
    "registration_promoted",
    "registration_attended",
)
BOOKINGS_KEYS = ("created", "confirmed", "rejected", "cancelled", "completed", "no_show")
MAINTENANCE_KEYS = (
    "schedule_created",
    "schedule_updated",
    "schedule_deactivated",
    "logged",
    "schedule_completed",
)
MEMBERSHIP_KEYS = ("request_pending", "member_joined")

FABLAB_STREAM_KEYS = {
    "events": EVENTS_KEYS,
    "bookings": BOOKINGS_KEYS,
    "maintenance": MAINTENANCE_KEYS,
    "membership": MEMBERSHIP_KEYS,
}

# The feature key a stream belongs to. They differ for exactly one pair, which is why this
# mapping exists rather than being assumed equal at every call site.
STREAM_FOR_FEATURE = {
    "events": "events",
    "bookings": "bookings",
    "maintenance": "maintenance",
    "members": "membership",
}

MAKERSPACE_FIELDS = [
    {"name": "makerspace.name", "description": "Makerspace name."},
    {"name": "makerspace.location", "description": "Makerspace location label."},
    {"name": "makerspace.map_url", "description": "Google Maps link for the makerspace."},
    {"name": "event_name", "description": "Lifecycle event that triggered this email."},
    {"name": "now", "description": "Current render time."},
]

EVENTS_FIELDS = [
    {"name": "event.id", "description": "Event number."},
    {"name": "event.title", "description": "Event title."},
    {"name": "event.status", "description": "Current event status."},
    {"name": "event.when", "description": "Formatted start-to-end time."},
    {"name": "event.location", "description": "Event location, when set."},
    {"name": "registration.id", "description": "Registration number, when one applies."},
    {"name": "registration.name", "description": "Registrant name, when one applies."},
    {"name": "registration.status", "description": "Registration status."},
    {"name": "next_steps", "description": "Default guidance sentence for this event."},
    *MAKERSPACE_FIELDS,
]

BOOKINGS_FIELDS = [
    {"name": "booking.id", "description": "Booking number."},
    {"name": "booking.status", "description": "Current booking status."},
    {"name": "booking.name", "description": "Name the booking was made under."},
    {"name": "booking.when", "description": "Formatted start-to-end time."},
    {"name": "booking.space.name", "description": "Bookable space name."},
    {"name": "next_steps", "description": "Default guidance sentence for this event."},
    *MAKERSPACE_FIELDS,
]

MAINTENANCE_FIELDS = [
    {"name": "machine.id", "description": "Machine number."},
    {"name": "machine.name", "description": "Machine name."},
    {"name": "schedule.id", "description": "Maintenance schedule number, when one applies."},
    {"name": "schedule.description", "description": "Schedule description."},
    {"name": "schedule.next_due", "description": "Next due date for the schedule."},
    {"name": "schedule.is_active", "description": "Whether the schedule is active."},
    {"name": "log.id", "description": "Maintenance log number, when one applies."},
    {"name": "log.summary", "description": "Work summary recorded on the log."},
    {"name": "log.performed_at", "description": "When the work was performed."},
    {"name": "log.parts_note", "description": "Parts note recorded on the log."},
    {"name": "next_steps", "description": "Default guidance sentence for this event."},
    *MAKERSPACE_FIELDS,
]

MEMBERSHIP_FIELDS = [
    {"name": "member.name", "description": "Member display name."},
    {"name": "member.username", "description": "Member account username."},
    {"name": "member.email", "description": "Member account email."},
    {"name": "request.id", "description": "Membership request number, when one applies."},
    {"name": "request.applicant", "description": "Applicant name on a pending request."},
    *MAKERSPACE_FIELDS,
]


def _sample(bag, event_name, **extra):
    makerspace = bag(
        name="TinkerSpace",
        location="Demo Lab, Main Street",
        map_url="https://maps.google.com/?q=TinkerSpace",
    )
    return {
        "makerspace": makerspace,
        "event_name": event_name,
        "now": datetime(2026, 6, 21, 12, 0, tzinfo=timezone.utc),
        **extra,
    }


def _events_sample(bag, key):
    return _sample(
        bag,
        key,
        event=bag(
            id=12,
            title="Laser cutter induction",
            status="published",
            when="21 June 2026 18:00 to 20:00",
            location="Main workshop",
        ),
        registration=bag(id=5, name="Alex Maker", status="confirmed"),
        next_steps=EVENTS_REQUESTER_BODIES[key],
    )


def _bookings_sample(bag, key):
    return _sample(
        bag,
        key,
        booking=bag(
            id=31,
            status="confirmed",
            name="Alex Maker",
            when="21 June 2026 18:00 to 20:00",
            space=bag(name="Woodshop bench 2"),
        ),
        next_steps=BOOKINGS_REQUESTER_BODIES[key],
    )


def _maintenance_sample(bag, key):
    return _sample(
        bag,
        key,
        machine=bag(id=7, name="Laser cutter"),
        schedule=bag(
            id=3,
            description="Clean optics and check alignment",
            next_due="2026-07-01",
            is_active=True,
        ),
        log=bag(
            id=9,
            summary="Replaced the focus lens",
            performed_at=datetime(2026, 6, 20, 9, 30, tzinfo=timezone.utc),
            parts_note="Lens 50.8mm",
        ),
        next_steps=MAINTENANCE_REQUESTER_BODIES[key],
    )


def _membership_sample(bag, key):
    return _sample(
        bag,
        key,
        member=bag(name="Alex Maker", username="alex", email="alex@example.com"),
        request=bag(id=4, applicant="alex"),
    )


_SAMPLES = {
    "events": _events_sample,
    "bookings": _bookings_sample,
    "maintenance": _maintenance_sample,
    "membership": _membership_sample,
}

_FIELDS = {
    "events": EVENTS_FIELDS,
    "bookings": BOOKINGS_FIELDS,
    "maintenance": MAINTENANCE_FIELDS,
    "membership": MEMBERSHIP_FIELDS,
}

_STAFF_SUBJECTS = {
    "events": lambda key: EVENTS_STAFF_SUBJECT,
    "bookings": lambda key: BOOKINGS_STAFF_SUBJECT,
    "maintenance": lambda key: MAINTENANCE_STAFF_SUBJECT,
    "membership": lambda key: MEMBERSHIP_STAFF_SUBJECTS[key],
}

_STAFF_TEXTS = {
    "events": lambda key: EVENTS_STAFF_TEXT,
    "bookings": lambda key: BOOKINGS_STAFF_TEXT,
    "maintenance": lambda key: MAINTENANCE_STAFF_TEXT,
    "membership": lambda key: MEMBERSHIP_STAFF_TEXTS[key],
}

_REQUESTER_SUBJECTS = {
    "events": lambda key: EVENTS_REQUESTER_SUBJECTS[key],
    "bookings": lambda key: BOOKINGS_REQUESTER_SUBJECT,
    "maintenance": lambda key: MAINTENANCE_REQUESTER_SUBJECTS[key],
    "membership": lambda key: MEMBERSHIP_REQUESTER_SUBJECTS[key],
}

_REQUESTER_TEXTS = {
    "events": lambda key: EVENTS_REQUESTER_TEXT,
    "bookings": lambda key: BOOKINGS_REQUESTER_TEXT,
    "maintenance": lambda key: MAINTENANCE_REQUESTER_TEXT,
    "membership": lambda key: MEMBERSHIP_REQUESTER_TEXTS[key],
}


def build_entries(entry_cls, bag, label):
    """Every (stream, audience, key) entry for the four FabLab streams.

    Takes its collaborators as arguments rather than importing them: the caller is
    `email_templates_registry`, and importing back into it would be a cycle.
    """
    entries = {}
    for stream, keys in FABLAB_STREAM_KEYS.items():
        for key in keys:
            sample = _SAMPLES[stream](bag, key)
            entries[(stream, "staff", key)] = entry_cls(
                label=label(key),
                description=f"Staff email for {stream} event '{key}'.",
                fields=_FIELDS[stream],
                default_subject=_STAFF_SUBJECTS[stream](key),
                default_text=_STAFF_TEXTS[stream](key),
                default_html="",
                sample_context=sample,
            )
            entries[(stream, "requester", key)] = entry_cls(
                label=label(key),
                description=f"Member email for {stream} event '{key}'.",
                fields=_FIELDS[stream],
                default_subject=_REQUESTER_SUBJECTS[stream](key),
                default_text=_REQUESTER_TEXTS[stream](key),
                default_html="",
                sample_context=sample,
            )
    return entries
