"""Calendar recurrence retains phase; missed intervals are skipped in one step."""

from datetime import timedelta

from rest_framework.exceptions import ValidationError

from apps.makerspaces.local_time import to_local
from .models import MaintenanceSchedule


def clean_anchor(value):
    if value not in MaintenanceSchedule.Anchor.values:
        raise ValidationError({"anchor": "Choose completion or calendar."})
    return value


def next_due_after_completion(schedule, performed_at):
    completed = to_local(schedule.machine.makerspace, performed_at).date()
    try:
        if schedule.anchor == MaintenanceSchedule.Anchor.COMPLETION:
            return completed + timedelta(days=schedule.interval_days)
        # Always advance at least one occurrence, including an early completion.
        steps = max(1, (completed - schedule.next_due).days // schedule.interval_days + 1)
        return schedule.next_due + timedelta(days=steps * schedule.interval_days)
    except OverflowError as exc:
        raise ValidationError({"interval_days": "The next due date is outside the supported range."}) from exc
