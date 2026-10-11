"""Stocktake policy snapshots and idempotent F1 scheduled session creation."""

from datetime import timedelta

from django.db import transaction
from django.db.models import Q
from rest_framework.exceptions import ValidationError

from apps.accounts import rbac
from apps.audit.services import record
from apps.makerspaces.local_time import local_day_bounds, to_local
from apps.makerspaces.platform import feature_enabled
from .models_stocktake_discipline import StocktakePolicy, StocktakeSchedule
from .reminder_types import ReminderMessage, ReminderSource, ReminderSubject


def session_policy(space, data, actor=None):
    if not feature_enabled(space, "stocktake.discipline"):
        if data.get("blind"):
            raise ValidationError({"blind": "Stocktake discipline is disabled."})
        return {"blind": False, "variance_threshold": None}
    rows = StocktakePolicy.objects.all()
    rows = rbac.scope_by_action(actor, rbac.Action.EDIT_INVENTORY, rows) if actor else (
        rbac.scope_for_scheduled_work(rows, makerspace_id=space.pk))
    policy = rows.filter(makerspace=space).first()
    return {"blind": data.get("blind", policy.blind_default if policy else False),
            "variance_threshold": policy.variance_threshold if policy else None}


def needs_approval(session):
    threshold = session.variance_threshold
    return threshold is None or session.lines.filter(
        Q(variance_quantity__gt=threshold) | Q(variance_quantity__lt=-threshold),
    ).exists()


def schedules(space):
    return rbac.scope_for_scheduled_work(StocktakeSchedule.objects.all(),
                                         makerspace_id=space.pk).filter(is_active=True)


def discover(space, now, limit, local_tz):
    for row in schedules(space).filter(next_due__lte=to_local(space, now).date()).order_by("next_due", "pk")[:limit]:
        yield ReminderSubject(f"{row.pk}:{row.next_due}", "count", local_day_bounds(space, row.next_due)[0])


def current(space, reminder, *, lock=False):
    pk, day = reminder.subject.split(":", 1)
    rows = schedules(space)
    return (rows.select_for_update() if lock else rows).filter(pk=pk, next_due=day).first()


def build(space, reminder, now, local_tz):
    row = current(space, reminder)
    return ReminderMessage(row.name, "stocktake.scheduled") if row else None


@transaction.atomic
def dispatch(space, reminder, message, now, local_tz):
    from .models import StocktakeSession
    from apps.notifications.emit import emit_notification
    row = current(space, reminder, lock=True)
    if row is None:
        return None
    values = session_policy(space, {"blind": row.blind})
    session = StocktakeSession.objects.create(makerspace=space, container=row.container,
                                              notes=row.name, **values)
    # Calendar anchored, skipping missed intervals rather than opening many sessions.
    today = to_local(space, now).date()
    row.next_due += timedelta(days=(max(0, (today-row.next_due).days)//row.interval_days+1)*row.interval_days)
    row.save(update_fields=["next_due"])
    record(None, "stocktake.scheduled", makerspace=space, target=session)
    emit_notification(space, title=message.title, event=message.event,
                      body="A scheduled stocktake is ready for counting.", level="info")


SOURCE = ReminderSource("stocktake.scheduled", "stocktake", discover, build,
                        "stocktake.discipline", dispatch, requires_notifications=False)
