"""Calendar-day safety reminders, one pair per schedule due-date occurrence."""

from datetime import timedelta

from django.db.models import CharField, Value, Q
from django.db.models.functions import Cast, Concat

from apps.accounts import rbac
from apps.machines.reminder_policy import policy_values, policy_window
from apps.makerspaces.local_time import local_day_bounds, to_local
from apps.operations.reminder_consumer_queries import unfinished
from apps.operations.reminder_registry import ReminderMessage, ReminderSubject
from .models import MaintenanceSchedule
from .notifications import notify_maintenance_lifecycle

SOURCE = "maintenance.due"


def schedules(makerspace):
    return rbac.scope_for_scheduled_work(
        MaintenanceSchedule.objects.select_related("machine__makerspace", "machine__machine_type"),
        makerspace_id=makerspace.pk, field="machine__makerspace_id",
    ).filter(is_active=True, machine__is_active=True)


def reminder_time(makerspace, schedule, kind):
    policy = policy_values(makerspace, schedule.machine.machine_type_id)
    if kind == "due_soon" and not policy["reminder_lead_days"]:
        return None
    days = -policy["reminder_lead_days"] if kind == "due_soon" else policy["grace_days"] + 1
    return local_day_bounds(makerspace, schedule.next_due + timedelta(days=days))[0]


def discover(makerspace, now, limit, local_tz):
    today = to_local(makerspace, now).date()
    # Discovery is capped across kinds by the sweeper; drain overdue work first.
    for kind in ("overdue", "due_soon"):
        rows = unfinished(schedules(makerspace).exclude(trigger="usage"), makerspace, SOURCE, kind,
                          Concat(Cast("pk", CharField()), Value(":"), Cast("next_due", CharField())))
        window = policy_window(
            makerspace, "reminder_lead_days" if kind == "due_soon" else "grace_days", "machine__machine_type_id",
            lambda days: (Q(next_due__gte=today, next_due__lte=today + timedelta(days=days)) if days else Q(pk__in=[]))
            if kind == "due_soon" else Q(next_due__lt=today - timedelta(days=days)),
        )
        for schedule in rows.filter(window).order_by("next_due", "pk")[:limit]:
            due = reminder_time(makerspace, schedule, kind)
            # A missed advance notice should not follow an overdue notice.
            if kind == "due_soon" and schedule.next_due < to_local(makerspace, now).date():
                continue
            if due is not None and due <= now:
                yield ReminderSubject(schedule.reminder_subject, kind, due)


def build(makerspace, reminder, now, local_tz):
    if reminder.kind not in ("due_soon", "overdue") or reminder.offset_seconds != 0:
        return None
    pk, day = reminder.subject.split(":", 1)
    schedule = schedules(makerspace).exclude(trigger="usage").filter(pk=pk, next_due=day).first()
    if schedule is None or reminder_time(makerspace, schedule, reminder.kind) != reminder.due_at:
        return None
    if reminder.kind == "due_soon" and schedule.next_due < to_local(makerspace, now).date():
        return None
    return ReminderMessage(title=schedule.machine.name, event=reminder.kind,
                           body=f"Maintenance due {schedule.next_due.isoformat()}")


def dispatch(makerspace, reminder, message):
    pk, day = reminder.subject.split(":", 1)
    schedule = schedules(makerspace).exclude(trigger="usage").filter(pk=pk, next_due=day).first()
    if schedule:
        notify_maintenance_lifecycle(schedule, message.event)
