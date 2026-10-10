"""Explicit registrations of scoped, live-revalidated reminder sources."""

from .reminder_types import ReminderMessage, ReminderSource, ReminderSubject

# Consumer lanes add sources explicitly; there is no dynamic autodiscovery.
from apps.hardware_requests.loan_reminders import LOAN_REMINDER_SOURCES  # noqa: E402

REMINDER_SOURCES: tuple[ReminderSource, ...] = LOAN_REMINDER_SOURCES


def registered_sources():
    from apps.makerspaces.capabilities import FEATURES
    from apps.makerspaces.module_registry import MODULE_KEYS

    seen = set()
    for source in REMINDER_SOURCES:
        if not isinstance(source.key, str) or not source.key.strip() or len(source.key) > 80:
            raise ValueError("Reminder source needs a nonempty key of at most 80 characters.")
        if source.key in seen:
            raise ValueError(f"Duplicate reminder source: {source.key}")
        if source.module not in MODULE_KEYS or (
            source.feature is not None and source.feature not in FEATURES
        ):
            raise ValueError(f"Unknown reminder source gate: {source.key}")
        if not callable(source.discover) or not callable(source.build):
            raise ValueError(f"Reminder source callbacks are required: {source.key}")
        if source.dispatch is not None and not callable(source.dispatch):
            raise ValueError(f"Reminder source dispatcher must be callable: {source.key}")
        if type(source.requires_notifications) is not bool:
            raise ValueError(f"Reminder notifications gate must be boolean: {source.key}")
        seen.add(source.key)
    return REMINDER_SOURCES
