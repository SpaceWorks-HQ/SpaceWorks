"""Contracts for explicit reminder consumers, independent of the source registry."""

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
    # Member consumers use the notification matrix rather than the staff inbox.
    dispatch: Callable[[Makerspace, ReminderSchedule, ReminderMessage], NotificationResult | None] | None = None
