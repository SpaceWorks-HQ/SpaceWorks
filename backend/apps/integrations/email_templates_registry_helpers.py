from dataclasses import dataclass
from datetime import datetime, timezone
from types import SimpleNamespace

from django.core.exceptions import ValidationError


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
