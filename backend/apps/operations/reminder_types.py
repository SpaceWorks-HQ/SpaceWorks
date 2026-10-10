"""Reminder contracts shared by the registry and its explicit domain sources."""

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
    # A domain dispatcher runs after the live tenant gate check. None keeps the
    # foundation's staff-inbox emitter for sources that already use it.
    dispatch: Callable[[Makerspace, ReminderSchedule, ReminderMessage, datetime, tzinfo], None] | None = None
