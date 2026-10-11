"""Explicit registrations for the shared reminder sweep.

Sources discover scoped domain subjects and rebuild messages at dispatch time so
cancelled/returned subjects do not receive stale notifications. See the test-only
example in tests/operations/reminder_example.py and docs/reminder-schedules.md.
"""

from apps.operations.reminder_types import (  # noqa: F401 - explicit compatibility exports
    ReminderMessage, ReminderSource, ReminderSubject,
)


# No AppConfig hooks or autodiscovery: production consumers register here explicitly.
from apps.operations.membership_payment_reminders import MEMBERSHIP_PAYMENT_SOURCE

def _production_sources():
    from apps.makerspaces.membership_renewal_reminders import MEMBERSHIP_RENEWAL_SOURCE
    from apps.payments.reminders import build_payment_message, discover_payments, dispatch_payment_message
    return (MEMBERSHIP_PAYMENT_SOURCE, MEMBERSHIP_RENEWAL_SOURCE, ReminderSource(
        key="payments.due", module="request_workflow", feature="billing.reminders",
        discover=discover_payments, build=build_payment_message, dispatch=dispatch_payment_message,
    ))


# Tests can override production registrations; an empty tuple disables all sources.
REMINDER_SOURCES: tuple[ReminderSource, ...] | None = None


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
