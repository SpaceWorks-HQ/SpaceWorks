"""Reminder contracts shared by the registry and its explicit domain sources."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, tzinfo
from typing import TYPE_CHECKING, Callable, Iterable

if TYPE_CHECKING:
    from apps.integrations.notify import NotificationResult

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
    # None keeps the staff-inbox emitter. A dispatcher may return delivery results;
    # legacy callbacks returning None count attempts because they have no receipt.
    dispatch: Callable[[Makerspace, ReminderSchedule, ReminderMessage, datetime, tzinfo], NotificationResult | None] | None = None
    requires_notifications: bool = True
