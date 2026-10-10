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
    # Domain adapters can deliver borrower mail through the notification matrix.
    # The default stays the F1 staff-inbox emitter for existing consumers.
    dispatch: Callable | None = None
    requires_notifications: bool = True


