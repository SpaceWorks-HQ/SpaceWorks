"""Exclude terminal occurrences in SQL before applying a discovery batch limit."""

from apps.accounts import rbac
from .models_reminders import ReminderSchedule


def unfinished(queryset, makerspace, source, kind, subject_expression):
    final = rbac.scope_for_scheduled_work(
        ReminderSchedule.objects.all(), makerspace_id=makerspace.pk,
    ).filter(source=source, kind=kind, offset_seconds=0).exclude(
        state=ReminderSchedule.State.PENDING,
    ).values("subject")
    return queryset.annotate(reminder_subject=subject_expression).exclude(reminder_subject__in=final)
