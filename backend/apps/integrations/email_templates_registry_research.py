"""F3 templates: explicit fields, no model objects, contacts or provider handles.

Staff payment context deliberately omits amounts: chat uses the staff registry entry.
Only the requester's own payment email receives amount/currency fields.
"""

from .email_templates_registry_helpers import EmailTemplateRegistryEntry, bag


FAMILY_EVENTS = {
    "payments": ("charge_raised", "payment_due_soon", "payment_due_today", "payment_overdue",
                 "payment_received", "refund_issued", "payment_failed"),
    "membership": ("approved", "declined", "renewal_due", "lapsed", "renewal_failed", "awaiting_payment", "payment_due",
                   "renewed", "grace_started", "cancelled"),
    "stock": ("low_stock", "procurement_received"),
    "maintenance": ("due_soon", "overdue"),
    "certifications": ("granted", "revoked", "expiring", "expired"),
}

# Stock and maintenance are staff operational alerts. The research names financial,
# membership lifecycle and certification expiry communication to the affected member.
REQUESTER_EVENTS = {
    "payments": frozenset(FAMILY_EVENTS["payments"]),
    "membership": frozenset(FAMILY_EVENTS["membership"]),
    "certifications": frozenset({"expiring", "expired"}),
}

SUBJECT_FIELDS = {
    "payments": ("id", "status"),
    "membership": ("id", "status"),
    "stock": ("id", "name"),
    "certifications": ("id", "name", "expires_at"),
}

STAFF_TEXT = {
    "payments": "Payment #{{ subject.id }}: {{ event_name }}. Status: {{ subject.status }}.",
    "membership": "Membership #{{ subject.id }}: {{ event_name }}. Status: {{ subject.status }}.",
    "stock": "Stock item #{{ subject.id }} ({{ subject.name }}): {{ event_name }}.",
    "maintenance": "Maintenance schedule #{{ schedule.id }} for {{ machine.name }}: "
                   "{{ event_name }}. Due: {{ schedule.next_due }}.",
    "certifications": "Certification #{{ subject.id }} ({{ subject.name }}): "
                      "{{ event_name }}. Expiry: {{ subject.expires_at }}.",
}

REQUESTER_TEXT = {
    "payments": "Your payment #{{ subject.id }}: {{ event_name }}. "
                "Amount: {{ subject.amount }} {{ subject.currency }}. "
                "{% if subject.due_date %}Due: {{ subject.due_date }}. {% endif %}"
                "Review your payment history at {{ makerspace.name }}.",
    "membership": "Your membership at {{ makerspace.name }}: {{ event_name }}.",
    "certifications": "Your certification {{ subject.name }} at {{ makerspace.name }}: "
                      "{{ event_name }}. Expiry: {{ subject.expires_at }}.",
}


def build_entries():
    entries = {}
    for stream, events in FAMILY_EVENTS.items():
        for event in events:
            audiences = ["staff"]
            if event in REQUESTER_EVENTS.get(stream, ()):
                audiences.append("requester")
            for audience in audiences:
                names = [f"subject.{key}" for key in SUBJECT_FIELDS.get(stream, ())]
                sample = {
                    "makerspace": bag(name="Demo workshop"), "event_name": event,
                    "subject": bag(id=12, status="pending", name="Laser induction",
                                   expires_at="2026-11-10T12:00:00Z"),
                }
                if stream == "maintenance":
                    names = ["schedule.id", "schedule.next_due", "machine.name"]
                    sample.update(schedule=bag(id=12, next_due="2026-11-10"),
                                  machine=bag(name="Laser cutter"))
                if stream == "payments" and audience == "requester":
                    names += ["subject.amount", "subject.currency", "subject.due_date"]
                    sample["subject"] = bag(id=12, status="pending", amount="25.00", currency="USD", due_date="2026-11-10")
                text = STAFF_TEXT[stream] if audience == "staff" else REQUESTER_TEXT[stream]
                entries[(stream, audience, event)] = EmailTemplateRegistryEntry(
                    label=event.replace("_", " ").capitalize(),
                    description=f"{audience.capitalize()} notice for {stream}: {event}.",
                    fields=[{"name": name, "description": "Bounded event snapshot."}
                            for name in [*names, "makerspace.name", "event_name"]],
                    default_subject=f"{stream.capitalize()}: {event.replace('_', ' ')}",
                    default_text=text, default_html="", sample_context=sample,
                )
    return entries
