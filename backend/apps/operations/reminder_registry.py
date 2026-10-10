"""Explicit registrations only. Domain consumers use the shared F1 scheduler.

Sources discover scoped domain subjects and rebuild messages at dispatch time so
cancelled/returned subjects do not receive stale notifications. See the test-only
example in tests/operations/reminder_example.py and docs/reminder-schedules.md.
"""

from apps.operations.reminder_types import ReminderMessage, ReminderSource, ReminderSubject


# None selects the explicitly declared runtime consumers; a tuple is an exact
# override (including the empty tuple), keeping test-only sources isolated.
REMINDER_SOURCES: tuple[ReminderSource, ...] | None = None


def _production_sources():
    from apps.separability.registry import runtime_active

    sources = []
    # Operations is core: importing it must never load a tombstoned app's runtime.
    # Explicit lazy imports preserve the registry rather than doing autodiscovery.
    if runtime_active("events"):
        from apps.events.reminders import EVENT_REMINDER_SOURCE

        sources.append(EVENT_REMINDER_SOURCE)
    if runtime_active("bookings"):
        from apps.bookings.reminders import BOOKING_REMINDER_SOURCE

        sources.append(BOOKING_REMINDER_SOURCE)
    return tuple(sources)


def registered_sources():
    from apps.makerspaces.capabilities import FEATURES
    from apps.makerspaces.module_registry import MODULE_KEYS

    sources = _production_sources() if REMINDER_SOURCES is None else REMINDER_SOURCES
    seen = set()
    for source in sources:
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
            raise ValueError(f"Reminder dispatch callback must be callable: {source.key}")
        seen.add(source.key)
    return sources
