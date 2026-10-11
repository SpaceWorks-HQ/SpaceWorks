"""F1 renewal work and deduplicated local-calendar reminder steps."""
from datetime import timedelta

from django.db.models import Exists, OuterRef

from apps.accounts import rbac
from apps.makerspaces.local_time import local_day_bounds, to_local
from apps.makerspaces.models import MembershipTerm
from apps.makerspaces.platform import feature_enabled
from apps.makerspaces.membership_renewals import grace_end, run_membership_renewals
from apps.operations.models_reminders import ReminderSchedule
from apps.operations.reminder_types import ReminderMessage, ReminderSource, ReminderSubject

SOURCE = "membership.renewal"


def _schedules(space):
    return rbac.scope_for_scheduled_work(ReminderSchedule.objects.all(), makerspace_id=space.pk)


def _terms(space):
    return rbac.scope_for_scheduled_work(
        MembershipTerm.objects.select_related("plan", "membership__makerspace", "membership__user"),
        makerspace_id=space.pk, field="membership__makerspace_id",
    ).filter(membership__status="active", membership__renewal_cancelled_at__isnull=True,
             plan__auto_renew=True, status__in=("active", "expired"), next_term__isnull=True,
             membership__user__is_active=True, membership__user__access_status="active")


def _steps(space, term):
    expiry = to_local(space, term.ends_at).date()
    days = sorted({*[-day for day in term.plan.reminder_days_before], 0,
                   *term.plan.reminder_days_after})
    steps = [(f"day:{day}", local_day_bounds(space, expiry + timedelta(days=day))[0]) for day in days]
    if grace_end(term) > term.ends_at:
        steps.append(("grace_started", term.ends_at))
    # Lapse is an exact grace boundary, rather than midnight before grace finishes.
    steps.append(("lapsed", grace_end(term)))
    return steps


def discover(space, now, limit, local_tz):
    run_membership_renewals(now=now, limit=limit, makerspace_id=space.pk)
    if not feature_enabled(space, "membership.lifecycle_mail"):
        return
    complete = _schedules(space).filter(source=SOURCE, kind="lapsed")
    # Lapse is scheduled last: its existence proves discovery finished this subject.
    # Bound inspected subjects too, so completed histories cannot cause empty scans.
    from django.db.models.functions import Cast
    from django.db.models import CharField
    terms = _terms(space).annotate(subject_key=Cast("pk", CharField()))
    complete = complete.filter(subject=OuterRef("subject_key"))
    terms = terms.annotate(complete_schedule=Exists(complete)).filter(complete_schedule=False)
    for term in terms.order_by("ends_at", "pk")[:limit]:
        finished = set(_schedules(space).filter(source=SOURCE,
                            subject=str(term.pk)).values_list("kind", flat=True))
        for kind, at in _steps(space, term):
            if kind not in finished:
                yield ReminderSubject(str(term.pk), kind, at)


def _current(space, reminder, now):
    if not feature_enabled(space, "membership.lifecycle_mail") or not reminder.subject.isdecimal():
        return None
    term = _terms(space).filter(pk=int(reminder.subject)).first()
    if term is None or (reminder.kind, reminder.due_at) not in _steps(space, term):
        return None
    if reminder.kind == "lapsed":
        return term if now >= grace_end(term) else None
    if reminder.kind == "grace_started":
        return term if term.ends_at <= now < grace_end(term) else None
    due = [step for step in _steps(space, term) if step[0] != "lapsed" and step[1] <= now]
    if not due or reminder.due_at != max(at for _, at in due):
        return None
    if reminder.kind.startswith("day:-") and to_local(space, now).date() != to_local(space, reminder.due_at).date():
        return None
    return term


def build(space, reminder, now, local_tz):
    term = _current(space, reminder, now)
    if term is None:
        return None
    event = "lapsed" if reminder.kind == "lapsed" else "renewal_due"
    if reminder.kind == "grace_started":
        event = "grace_started"
    return ReminderMessage(title="Membership renewal", event=event)


def dispatch(space, reminder, message, now, local_tz):
    from apps.makerspaces.membership_renewal_notifications import notify_term
    term = _current(space, reminder, now)
    if term:
        notify_term(term, message.event)


MEMBERSHIP_RENEWAL_SOURCE = ReminderSource(
    key=SOURCE, module="membership", feature="membership.auto_renew",
    discover=discover, build=build, dispatch=dispatch,
)
