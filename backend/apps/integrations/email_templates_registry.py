from dataclasses import dataclass
from datetime import datetime, timezone
from types import SimpleNamespace

from django.core.exceptions import ValidationError
from django.template import Context, Template, TemplateSyntaxError

from .email_templates_registry_fablab import build_entries as _build_fablab_entries
from .email_templates_registry_defaults import (
    HARDWARE_REQUESTER_DEFAULTS,
    HARDWARE_STAFF_DEFAULTS,
    PRINTING_REQUESTER_HTML,
    PRINTING_REQUESTER_SUBJECTS,
    PRINTING_REQUESTER_TEXT,
    PRINTING_STAFF_SUBJECTS,
    PRINTING_STAFF_TEXT,
)

STREAMS = {"hardware", "printing", "events", "bookings", "maintenance", "membership"}
AUDIENCES = {"requester", "staff"}


class FrozenBag(SimpleNamespace):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        object.__setattr__(self, "_frozen", True)

    def __setattr__(self, name, value):
        if getattr(self, "_frozen", False):
            raise AttributeError("Email template context bags are frozen.")
        super().__setattr__(name, value)

    def __delattr__(self, name):
        if getattr(self, "_frozen", False):
            raise AttributeError("Email template context bags are frozen.")
        super().__delattr__(name)


def bag(**kwargs):
    return FrozenBag(**kwargs)


@dataclass(frozen=True)
class EmailTemplateRegistryEntry:
    label: str
    description: str
    fields: list[dict[str, str]]
    default_subject: str
    default_text: str
    default_html: str
    sample_context: dict[str, object]


HARDWARE_REQUESTER_KEYS = (
    "request_received",
    "request_accepted",
    "request_rejected",
    "request_issued",
    "request_returned",
    "return_reminder",
)
HARDWARE_STAFF_KEYS = (
    "submitted",
    "accepted",
    "rejected",
    "issued",
    "partially_returned",
    "returned",
    "closed_with_issue",
    "return_reminder",
)
PRINTING_REQUESTER_KEYS = ("submitted", "accepted", "started", "rejected", "completed")
PRINTING_STAFF_KEYS = (
    "submitted",
    "accepted",
    "started",
    "completed",
    "rejected",
    "failed",
    "collected",
    "reprinted",
)

HARDWARE_FIELDS = [
    {"name": "request.id", "description": "Hardware request number."},
    {"name": "request.status", "description": "Current request status."},
    {"name": "request.return_due_at", "description": "Due date/time for returned hardware."},
    {"name": "request.rejection_reason", "description": "Reason recorded when rejected."},
    {"name": "request.requester_name", "description": "Requester display name."},
    {"name": "request.requester_username", "description": "Requester Check-In username."},
    {"name": "request.requester_contact_email", "description": "Requester contact email."},
    {"name": "request.requester_contact_phone", "description": "Requester contact phone."},
    {"name": "request.requested_for", "description": "Requester-provided purpose."},
    {"name": "request.assigned_box.code", "description": "Assigned container code, when present."},
    {"name": "items", "description": "Requested item rows."},
    {"name": "item.product.name", "description": "Item product name inside an items loop."},
    {"name": "item.requested_quantity", "description": "Quantity requested inside an items loop."},
    {"name": "item.issued_quantity", "description": "Quantity issued inside an items loop."},
    {"name": "makerspace.name", "description": "Makerspace name."},
    {"name": "makerspace.location", "description": "Makerspace location label."},
    {"name": "makerspace.map_url", "description": "Google Maps link for the makerspace."},
    {"name": "now", "description": "Current render time."},
]
HARDWARE_STAFF_FIELDS = [
    *HARDWARE_FIELDS,
    {"name": "staff_summary", "description": "Pre-rendered staff-facing request summary."},
]
PRINTING_FIELDS = [
    {"name": "print_request.id", "description": "Print request number."},
    {"name": "print_request.status", "description": "Current print request status."},
    {"name": "print_request.title", "description": "Print request title."},
    {"name": "print_request.reason", "description": "Request/rejection/failure reason."},
    {"name": "print_request.material", "description": "Requested material."},
    {"name": "print_request.color", "description": "Requested color."},
    {"name": "print_request.quantity", "description": "Requested print quantity."},
    {"name": "print_request.requester_name", "description": "Requester display name."},
    {"name": "print_request.contact_email", "description": "Requester contact email."},
    {"name": "print_request.contact_phone", "description": "Requester contact phone."},
    {"name": "print_request.reprint_of_id", "description": "Original request number for reprints."},
    {"name": "print_request.requester.username", "description": "Requester account username."},
    {"name": "print_request.requester.email", "description": "Requester account email."},
    {"name": "print_request.bucket.name", "description": "Print bucket name."},
    {"name": "print_request.bucket.makerspace.name", "description": "Makerspace name."},
    {"name": "print_request.bucket.makerspace.location", "description": "Makerspace location label."},
    {"name": "print_request.bucket.makerspace.map_url", "description": "Google Maps link."},
    {"name": "makerspace.name", "description": "Makerspace name."},
    {"name": "makerspace.location", "description": "Makerspace location label."},
    {"name": "makerspace.map_url", "description": "Google Maps link for the makerspace."},
    {"name": "status_url", "description": "Public print status URL."},
    {"name": "public_token", "description": "Public status tracking token."},
    {"name": "now", "description": "Current render time."},
]


def _hardware_sample_context(staff=False):
    makerspace = bag(
        name="TinkerSpace",
        location="Demo Lab, Main Street",
        map_url="https://maps.google.com/?q=TinkerSpace",
    )
    items = [
        bag(
            product=bag(name="Cordless Drill"),
            requested_quantity=2,
            issued_quantity=1,
        )
    ]
    request = bag(
        id=42,
        status="issued",
        return_due_at=datetime(2026, 6, 28, 18, 0, tzinfo=timezone.utc),
        rejection_reason="",
        requester_name="Alex Maker",
        requester_username="alex",
        requester_contact_email="alex@example.com",
        requester_contact_phone="+15550101010",
        requested_for="Workshop repair session",
        assigned_box=bag(code="BOX-7"),
        items=items,
        makerspace=makerspace,
    )
    context = {
        "request": request,
        "items": items,
        "makerspace": makerspace,
        "now": datetime(2026, 6, 21, 12, 0, tzinfo=timezone.utc),
    }
    if staff:
        context["staff_summary"] = (
            "Status: issued\n"
            "Requester: Alex Maker\n"
            "Email: alex@example.com\n"
            "Phone: +15550101010\n"
            "Box: BOX-7\n"
            "Return due: 2026-06-28 18:00:00+00:00"
        )
    return context


def _printing_sample_context():
    makerspace = bag(
        name="TinkerSpace",
        location="Demo Lab, Main Street",
        map_url="https://maps.google.com/?q=TinkerSpace",
    )
    print_request = bag(
        id=73,
        status="accepted",
        title="Replacement gear",
        reason="Prototype needs a tighter tolerance",
        material="PLA",
        color="Black",
        quantity=2,
        requester_name="Alex Maker",
        contact_email="alex@example.com",
        contact_phone="+15550101010",
        reprint_of_id=64,
        requester=bag(username="alex", email="alex.account@example.com"),
        bucket=bag(name="General prints", makerspace=makerspace),
    )
    context = {
        "print_request": print_request,
        "makerspace": makerspace,
        "status_url": "https://example.test/m/tinkerspace/print?token=abc123",
        "public_token": "abc123",
        "now": datetime(2026, 6, 21, 12, 0, tzinfo=timezone.utc),
    }
    return context


def _label(text):
    return text.replace("_", " ").capitalize()


def _hardware_requester_entry(key):
    defaults = HARDWARE_REQUESTER_DEFAULTS[key]
    return EmailTemplateRegistryEntry(
        label=_label(key),
        description=f"Requester email for hardware event '{key}'.",
        fields=HARDWARE_FIELDS,
        default_subject=defaults["subject"],
        default_text=defaults["text"],
        default_html=defaults.get("html", ""),
        sample_context=_hardware_sample_context(staff=False),
    )


def _hardware_staff_entry(key):
    defaults = HARDWARE_STAFF_DEFAULTS[key]
    return EmailTemplateRegistryEntry(
        label=_label(key),
        description=f"Staff email for hardware event '{key}'.",
        fields=HARDWARE_STAFF_FIELDS,
        default_subject=defaults["subject"],
        default_text=defaults["text"],
        default_html="",
        sample_context=_hardware_sample_context(staff=True),
    )


def _printing_requester_entry(key):
    return EmailTemplateRegistryEntry(
        label=_label(key),
        description=f"Requester email for printing event '{key}'.",
        fields=PRINTING_FIELDS,
        default_subject=PRINTING_REQUESTER_SUBJECTS[key],
        default_text=PRINTING_REQUESTER_TEXT[key],
        default_html=PRINTING_REQUESTER_HTML[key],
        sample_context=_printing_sample_context(),
    )


def _printing_staff_entry(key):
    return EmailTemplateRegistryEntry(
        label=_label(key),
        description=f"Staff email for printing event '{key}'.",
        fields=PRINTING_FIELDS,
        default_subject=PRINTING_STAFF_SUBJECTS[key],
        default_text=PRINTING_STAFF_TEXT.replace("{{ event }}", key),
        default_html="",
        sample_context=_printing_sample_context(),
    )


REGISTRY = {
    **{
        ("hardware", "requester", key): _hardware_requester_entry(key)
        for key in HARDWARE_REQUESTER_KEYS
    },
    **{
        ("hardware", "staff", key): _hardware_staff_entry(key)
        for key in HARDWARE_STAFF_KEYS
    },
    **{
        ("printing", "requester", key): _printing_requester_entry(key)
        for key in PRINTING_REQUESTER_KEYS
    },
    **{
        ("printing", "staff", key): _printing_staff_entry(key)
        for key in PRINTING_STAFF_KEYS
    },
    # The four FabLab streams, both audiences. Built by a helper in its own module so the
    # 40 authored bodies do not swamp this file; the entries are the same shape as the
    # ones above and go through the same validator.
    **_build_fablab_entries(EmailTemplateRegistryEntry, bag, _label),
}


def get_entry(stream, audience, key):
    return REGISTRY.get((stream, audience, key))


def iter_entries():
    return REGISTRY.items()


def all_send_keys():
    return set(REGISTRY)


def _validate_template_delimiters(value):
    for start, end in (("{{", "}}"), ("{%", "%}"), ("{#", "#}")):
        offset = 0
        while True:
            open_at = value.find(start, offset)
            if open_at == -1:
                break
            close_at = value.find(end, open_at + len(start))
            if close_at == -1:
                raise ValidationError(
                    f"Email template has invalid syntax: unclosed {start} tag."
                )
            offset = close_at + len(end)


def validate_email_template_strings(stream, audience, key, subject, text_body, html_body):
    entry = get_entry(stream, audience, key)
    if entry is None:
        raise ValidationError("Unknown email template stream, audience, or key.")

    context = Context(entry.sample_context, autoescape=True)
    values = [subject, text_body]
    if html_body:
        values.append(html_body)

    for value in values:
        try:
            _validate_template_delimiters(value or "")
            Template(value or "").render(context)
        except TemplateSyntaxError as exc:
            raise ValidationError(f"Email template has invalid syntax: {exc}") from exc
        except Exception as exc:
            raise ValidationError(f"Email template has invalid syntax: {exc}") from exc
