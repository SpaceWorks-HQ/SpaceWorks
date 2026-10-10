"""Explicit registrations; domain adapters are lazy for tombstone compatibility.

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
    # Domain consumers may dispatch through a member/scoped notification family.
    dispatch: Callable | None = None


# Consumer registration is explicit, with canonical module/feature gates.
from . import reminder_machine_sources as machines

REMINDER_SOURCES: tuple[ReminderSource, ...] = (
    ReminderSource("machines.certification_expiry", "machines", machines.discover_certifications,
                   machines.build_certification, "machines.certification_reminders", machines.dispatch_certification),
    ReminderSource("machines.certification_digest", "machines", machines.discover_digest,
                   machines.build_digest, "machines.certification_reminders", machines.dispatch_digest),
    ReminderSource("maintenance.due", "maintenance", machines.discover_maintenance,
                   machines.build_maintenance, "maintenance.reminders", machines.dispatch_maintenance),
)


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
            raise ValueError(f"Reminder dispatch callback is invalid: {source.key}")
        seen.add(source.key)
    return REMINDER_SOURCES
