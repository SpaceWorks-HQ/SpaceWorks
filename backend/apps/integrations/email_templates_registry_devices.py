"""Small device stream merged into the existing email/chat template registry."""

from .email_templates_registry_devices_defaults import DEFAULTS
from .email_templates_registry_helpers import EmailTemplateRegistryEntry, bag


def build_entries():
    fields = [
        {"name": f"device.{key}", "description": label}
        for key, label in (
            ("id", "Device identifier."), ("name", "Device name."),
            ("kind", "Device kind."), ("state", "Offline or recovered."),
            ("last_seen_at", "Last signed heartbeat time."),
            ("offline_since", "Offline threshold time."),
        )
    ] + [{"name": "now", "description": "State transition time."}]
    return {
        ("devices", "staff", event): EmailTemplateRegistryEntry(
            label=f"Device {event}", description=f"Staff alert when a device is {event}.",
            fields=fields, default_subject=subject, default_text=text, default_html="",
            sample_context={"device": bag(id="00000000-0000-0000-0000-000000000001",
                                          name="Label printer", kind="label_printer",
                                          state=event, last_seen_at="2026-10-10T10:00:00Z",
                                          offline_since="2026-10-10T10:05:00Z"),
                            "now": "2026-10-10T10:06:00Z"},
        )
        for event, (subject, text) in DEFAULTS.items()
    }
