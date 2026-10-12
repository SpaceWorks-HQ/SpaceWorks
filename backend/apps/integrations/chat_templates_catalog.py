"""Staff template contracts for notification events without an email template."""

from .email_templates_registry_helpers import EmailTemplateRegistryEntry, bag


EVENTS = {
    ("hardware_requests", "deposit_raised"): ("request", ("id", "status")),
    ("hardware_requests", "late_fee_raised"): ("request", ("id", "status")),
    ("hardware_requests", "back_available"): ("product", ("id", "name")),
    ("api_access", "api_key_request_resolved"): ("request", ("id", "status")),
}


def chat_only_entry(feature, event):
    contract = EVENTS.get((feature, event))
    if contract is None:
        return None
    subject, names = contract
    return EmailTemplateRegistryEntry(
        label=event.replace("_", " ").capitalize(),
        description=f"Staff chat notice for {feature}: {event}.",
        fields=[{"name": f"{subject}.{name}", "description": "Event snapshot."}
                for name in names] + [{"name": "makerspace.name", "description": "Makerspace name."}],
        default_subject=event.replace("_", " ").capitalize(),
        default_text="{{ makerspace.name }}: " + event.replace("_", " ") + ".",
        default_html="",
        sample_context={"makerspace": bag(name="Demo workshop"),
                        subject: bag(id=12, status="pending", name="Torque wrench")},
    )
