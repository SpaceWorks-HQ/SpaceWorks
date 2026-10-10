"""Daily, type-scoped staff counts. No member names or training notes in chat."""

from datetime import timedelta

from django.db.models import CharField, Value, Q
from django.db.models.functions import Cast, Concat

from apps.accounts import rbac
from apps.integrations.destinations import NotificationScope
from apps.integrations.email_templates_registry_helpers import bag
from apps.integrations.notifications_research import notify_family
from apps.makerspaces.local_time import local_day_bounds, to_local
from apps.operations.reminder_consumer_queries import unfinished
from apps.operations.reminder_registry import ReminderMessage, ReminderSubject
from .models import CertificationType
from .reminder_policy import policy_values, policy_window
from .reminders_certifications import eligible_grants

SOURCE = "machines.certification_digest"


def counts(makerspace, type_id, now):
    days = policy_values(makerspace, type_id)["cert_reminder_days"]
    if not days:
        return 0
    end = to_local(makerspace, now) + timedelta(days=days)
    return eligible_grants(makerspace).filter(certification_type__machine_type_id=type_id,
                                              expires_at__gt=now, expires_at__lte=end).count()


def discover(makerspace, now, limit, local_tz):
    day = to_local(makerspace, now).date()
    expiring = eligible_grants(makerspace).filter(expires_at__gt=now).filter(policy_window(
        makerspace, "cert_reminder_days", "certification_type__machine_type_id",
        lambda days: Q(expires_at__lte=to_local(makerspace, now) + timedelta(days=days)) if days else Q(pk__in=[]),
    )).values("certification_type__machine_type_id")
    rows = rbac.scope_for_scheduled_work(CertificationType.objects.all(), makerspace_id=makerspace.pk).filter(machine_type_id__in=expiring)
    # Distinct machine types before batching: several inductions share one digest.
    rows = rows.filter(is_active=True).values("machine_type_id").distinct()
    rows = unfinished(rows, makerspace, SOURCE, "expiring",
                      Concat(Cast("machine_type_id", CharField()), Value(":" + day.isoformat())))
    for row in rows.order_by("machine_type_id")[:limit]:
        if counts(makerspace, row["machine_type_id"], now):
            yield ReminderSubject(row["reminder_subject"], "expiring", local_day_bounds(makerspace, day)[0])


def build(makerspace, reminder, now, local_tz):
    type_id, day = reminder.subject.split(":", 1)
    if reminder.kind != "expiring" or reminder.offset_seconds != 0 or day != to_local(makerspace, now).date().isoformat():
        return None
    count = counts(makerspace, int(type_id), now)
    if not count:
        return None
    return ReminderMessage(title="Expiring certifications", event="expiring",
                           body=f"{count} certification(s) expire soon; review and renew training.")


def dispatch(makerspace, reminder, message):
    type_id = int(reminder.subject.split(":", 1)[0])
    notify_family(makerspace, "certifications", "expiring",
                  bag(id=type_id, name=message.body, expires_at="See certification roster"),
                  data={"machine_type_id": type_id}, scope=NotificationScope(machine_type=type_id))
