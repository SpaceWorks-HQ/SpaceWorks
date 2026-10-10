"""Explicit reminder registrations; consumers own domain delivery and eligibility.

Sources discover scoped domain subjects and rebuild messages at dispatch time so
cancelled/returned subjects do not receive stale notifications. See the test-only
example in tests/operations/reminder_example.py and docs/reminder-schedules.md.
"""

from dataclasses import dataclass
from datetime import datetime, tzinfo
from typing import Callable, Iterable

from apps.makerspaces.models import Makerspace
from apps.operations.models_reminders import ReminderSchedule


@dataclass(frozen=True)
class ReminderSubject:
    subject: str
    kind: str
    due_at: datetime
    # Signed integral seconds; callers translate their policy's hours/days once.
    offsets: tuple[int, ...] = (0,)


@dataclass(frozen=True)
class ReminderMessage:
    title: str
    event: str
    body: str = ""
    level: str = "info"
    url_path: str = ""


@dataclass(frozen=True)
class ReminderSource:
    key: str
    module: str
    discover: Callable[[Makerspace, datetime, int, tzinfo], Iterable[ReminderSubject]]
    build: Callable[[Makerspace, ReminderSchedule, datetime, tzinfo], ReminderMessage | None]
    feature: str | None = None
    dispatch: Callable | None = None


# No AppConfig hooks or autodiscovery. Tests can replace the explicit registry.
def _production_sources():
    from apps.payments.reminders import build_payment_message, discover_payments, dispatch_payment_message
    return (ReminderSource(
        key="payments.due", module="request_workflow", feature="billing.reminders",
        discover=discover_payments, build=build_payment_message, dispatch=dispatch_payment_message,
    ),)


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
            raise ValueError(f"Reminder source dispatch must be callable: {source.key}")
        seen.add(source.key)
    return sources
