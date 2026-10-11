from django.db.models import CharField, Value, Q, F
from django.db.models.functions import Cast, Concat

from apps.operations.reminder_types import ReminderMessage, ReminderSource, ReminderSubject
from apps.operations.reminder_consumer_queries import unfinished
from apps.makerspaces.platform import feature_enabled
from apps.makerspaces.local_time import to_local
from . import reminders
from .meters import meter_due, due_queryset


def discover(space, now, limit, local_tz):
    if not feature_enabled(space, "maintenance.meters"):
        return
    rows = due_queryset(reminders.schedules(space).exclude(trigger="days"), to_local(space, now).date())
    # Calendar-overdue rows are also returned by due_queryset. Only actual meter
    # occurrences may consume this source's bounded discovery slots.
    rows = rows.filter(Q(usage_hours__isnull=False, meter_hours__gte=F("usage_hours")) |
                       Q(job_count__isnull=False, meter_jobs__gte=F("job_count")))
    rows = unfinished(rows, space, "maintenance.meter", "overdue",
                      Concat(Cast("pk", CharField()), Value(":"), Cast("meter_started_at", CharField())))
    for schedule in rows.order_by("pk")[:limit]:
        if meter_due(schedule):
            yield ReminderSubject(schedule.reminder_subject,
                                  "overdue", schedule.meter_started_at)


def current(space, reminder):
    pk, occurrence = reminder.subject.split(":", 1)
    return reminders.schedules(space).filter(pk=pk, meter_started_at=occurrence).first()


def build(space, reminder, now, local_tz):
    row = current(space, reminder)
    if row is None or not meter_due(row):
        return None
    return ReminderMessage(row.machine.name, "overdue", "Usage-based maintenance is due.")


def dispatch(space, reminder, message, now, local_tz):
    row = current(space, reminder)
    if row and meter_due(row):
        reminders.notify_maintenance_lifecycle(row, "overdue", due_reason=message.body)


SOURCE = ReminderSource("maintenance.meter", "maintenance", discover, build,
                        "maintenance.reminders", dispatch)
