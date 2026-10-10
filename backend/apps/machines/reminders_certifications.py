"""One member expiry notice per grant and kind, rebuilt under the tenant boundary."""

from datetime import timedelta

from django.db.models import CharField, Exists, OuterRef, Q
from django.db.models.functions import Cast

from apps.accounts import rbac
from apps.makerspaces.local_time import to_local
from apps.operations.reminder_consumer_queries import unfinished
from apps.operations.reminder_registry import ReminderMessage, ReminderSubject
from .models import CertificationGrant
from .notifications_certifications import notify_certification
from .reminder_policy import policy_values, policy_window

SOURCE = "machines.certification_expiry"


def eligible_grants(makerspace):
    rows = rbac.scope_for_scheduled_work(
        CertificationGrant.objects.select_related("certification_type__machine_type", "membership__user"),
        makerspace_id=makerspace.pk, field="certification_type__makerspace_id",
    ).filter(certification_type__is_active=True, membership__makerspace=makerspace,
             membership__status="active", membership__user__is_active=True,
             membership__user__access_status="active", revoked_at__isnull=True,
             expires_at__isnull=False)
    # Any live grant satisfies the gate. Notify only the longest remaining window,
    # so a short renewal cannot announce expiry while an older grant still covers use.
    covering = rbac.scope_for_scheduled_work(
        CertificationGrant.objects.all(), makerspace_id=makerspace.pk,
        field="certification_type__makerspace_id",
    ).filter(membership_id=OuterRef("membership_id"),
             certification_type_id=OuterRef("certification_type_id"),
             revoked_at__isnull=True).exclude(pk=OuterRef("pk")).filter(
        Q(expires_at__isnull=True) | Q(expires_at__gt=OuterRef("expires_at")) |
        Q(expires_at=OuterRef("expires_at"), pk__gt=OuterRef("pk")),
    )
    return rows.annotate(superseded=Exists(covering)).filter(superseded=False)


def reminder_time(makerspace, grant, kind):
    if kind == "expired":
        return grant.expires_at
    days = policy_values(makerspace, grant.certification_type.machine_type_id)["cert_reminder_days"]
    return to_local(makerspace, grant.expires_at) - timedelta(days=days) if days else None


def discover(makerspace, now, limit, local_tz):
    # The shared sweeper caps the entire generator, not each kind. Safety notices
    # take priority so a stream of new advance notices cannot starve expired grants.
    for kind in ("expired", "expiring"):
        rows = unfinished(eligible_grants(makerspace), makerspace, SOURCE, kind,
                          Cast("pk", CharField()))
        rows = rows.filter(expires_at__gt=now).filter(policy_window(
            makerspace, "cert_reminder_days", "certification_type__machine_type_id",
            lambda days: Q(expires_at__lte=to_local(makerspace, now) + timedelta(days=days)) if days else Q(pk__in=[]),
        )) if kind == "expiring" else rows.filter(
            expires_at__lte=now,
        )
        for grant in rows.order_by("expires_at", "pk")[:limit]:
            due = reminder_time(makerspace, grant, kind)
            if due is not None and due <= now:
                yield ReminderSubject(str(grant.pk), kind, due, (0,))


def build(makerspace, reminder, now, local_tz):
    if reminder.kind not in ("expiring", "expired") or reminder.offset_seconds != 0:
        return None
    grant = eligible_grants(makerspace).filter(pk=reminder.subject).first()
    from apps.operations.reminder_services import utc_time
    due = reminder_time(makerspace, grant, reminder.kind) if grant else None
    if due is None or utc_time(due) != reminder.due_at:
        return None
    expired = grant.expires_at <= now
    if expired != (reminder.kind == "expired"):
        return None
    return ReminderMessage(title=grant.certification_type.name, event=reminder.kind,
                           body=to_local(makerspace, grant.expires_at).isoformat())


def dispatch(makerspace, reminder, message):
    grant = eligible_grants(makerspace).get(pk=reminder.subject)
    notify_certification(grant, message.event, include_staff=False)
