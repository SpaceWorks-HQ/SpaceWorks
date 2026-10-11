"""Explicit registrations of scoped, live-revalidated reminder sources."""

from apps.operations.reminder_types import (  # noqa: F401 - explicit compatibility exports
    ReminderMessage, ReminderSource, ReminderSubject,
)


# None selects production; a tuple is an exact override, including an empty tuple.
REMINDER_SOURCES: tuple[ReminderSource, ...] | None = None


def _production_sources():
    from apps.hardware_requests.loan_reminders import LOAN_REMINDER_SOURCES
    from apps.makerspaces.membership_renewal_reminders import MEMBERSHIP_RENEWAL_SOURCE
    from apps.operations.membership_payment_reminders import MEMBERSHIP_PAYMENT_SOURCE
    from apps.payments.reminders import build_payment_message, discover_payments, dispatch_payment_message
    from apps.separability.registry import runtime_active
    from . import reminder_machine_sources as machines

    from apps.integrations.reminders_deferred import DEFERRED_SOURCE

    sources = [DEFERRED_SOURCE, MEMBERSHIP_PAYMENT_SOURCE, MEMBERSHIP_RENEWAL_SOURCE, ReminderSource(
        key="payments.due", module="request_workflow", feature="billing.reminders",
        discover=discover_payments, build=build_payment_message, dispatch=dispatch_payment_message,
    ), *LOAN_REMINDER_SOURCES]
    # Core consumers always remain. Domain imports/registrations are runtime-only:
    # operations must load even when a separable domain app is tombstoned.
    if runtime_active("machines"):
        sources.extend((
            ReminderSource("machines.certification_expiry", "machines", machines.discover_certifications,
                           machines.build_certification, "machines.certification_reminders", machines.dispatch_certification),
            ReminderSource("machines.certification_digest", "machines", machines.discover_digest,
                           machines.build_digest, "machines.certification_reminders", machines.dispatch_digest),
        ))
    if runtime_active("maintenance"):
        sources.append(ReminderSource(
            "maintenance.due", "maintenance", machines.discover_maintenance,
            machines.build_maintenance, "maintenance.reminders", machines.dispatch_maintenance,
        ))
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
            raise ValueError(f"Reminder source dispatcher must be callable: {source.key}")
        if type(source.requires_notifications) is not bool:
            raise ValueError(f"Reminder notifications gate must be boolean: {source.key}")
        seen.add(source.key)
    return sources
