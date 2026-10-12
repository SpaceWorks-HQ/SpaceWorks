"""One applicant payment reminder before an admission request expires.

The awaiting-payment transition sends the initial notice. F1 coordinates a second,
deduplicated notice one day before the payment deadline, with live owner/status
checks at discovery, build and dispatch. Expiry/activation remains a domain service.
"""

from datetime import timedelta

from django.db.models import CharField, F
from django.db.models.functions import Cast

from apps.accounts import rbac
from apps.makerspaces.models import MembershipRequest
from apps.operations.models_reminders import ReminderSchedule
from apps.operations.reminder_types import ReminderMessage, ReminderSource, ReminderSubject
from apps.payments.models import Payment

SOURCE_KEY = "membership.admission_payment"
OFFSET = -24 * 60 * 60


def _requests(makerspace):
    return rbac.scope_for_scheduled_work(
        MembershipRequest.objects.all(), makerspace_id=makerspace.pk,
    ).filter(
        makerspace=makerspace, state="awaiting_payment",
        admission_payment__makerspace=makerspace,
        admission_payment__status=Payment.Status.PENDING,
        admission_payment__subject_type=Payment.SubjectType.MEMBERSHIP_REQUEST,
        admission_payment__subject_id=F("pk"), admission_payment__member_id=F("user_id"),
        user__isnull=False,
    )


def discover_payment_requests(makerspace, now, limit, local_tz):
    final_subjects = rbac.scope_for_scheduled_work(
        ReminderSchedule.objects.all(), makerspace_id=makerspace.pk,
    ).filter(
        source=SOURCE_KEY, kind="payment_due", offset_seconds=OFFSET,
    ).exclude(state=ReminderSchedule.State.PENDING).values("subject")
    requests = _requests(makerspace).filter(
        expires_at__gt=now, expires_at__lte=now + timedelta(days=1),
    ).annotate(reminder_subject=Cast("pk", CharField())).exclude(
        reminder_subject__in=final_subjects,
    ).order_by("expires_at", "pk")[:limit]
    for request in requests:
        yield ReminderSubject(str(request.pk), "payment_due", request.expires_at, (OFFSET,))


def _current_request(makerspace, reminder, now):
    if reminder.kind != "payment_due" or reminder.offset_seconds != OFFSET:
        return None
    if not reminder.subject.isdecimal():
        return None
    return _requests(makerspace).filter(
        pk=reminder.subject, expires_at=reminder.due_at, expires_at__gt=now,
    ).first()


def build_payment_message(makerspace, reminder, now, local_tz):
    request = _current_request(makerspace, reminder, now)
    if request is None:
        return None
    return ReminderMessage(
        title="Membership payment due", event="membership.payment_due",
    )


def dispatch_payment_message(makerspace, reminder, message, now, local_tz):
    from apps.makerspaces.membership_admission_notifications import notify_admission

    request = _current_request(makerspace, reminder, now)
    if request is not None:
        notify_admission(request, "payment_due")


MEMBERSHIP_PAYMENT_SOURCE = ReminderSource(
    key=SOURCE_KEY, module="membership", discover=discover_payment_requests,
    build=build_payment_message, dispatch=dispatch_payment_message,
)
