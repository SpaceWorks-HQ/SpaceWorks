"""F1 payment reminders: member email with durable at-most-once claims."""

from datetime import timedelta

from django.db.models import CharField, Exists, OuterRef, Q
from django.db.models.functions import Cast

from apps.accounts import rbac
from apps.makerspaces.local_time import local_day_bounds, to_local
from apps.makerspaces.platform import feature_enabled, module_enabled
from apps.operations.models_reminders import ReminderSchedule
from apps.operations.reminder_registry import ReminderMessage, ReminderSubject
from apps.payments.models import MakerspaceBillingSettings, Payment


def _days(makerspace):
    policy = rbac.scope_for_scheduled_work(
        MakerspaceBillingSettings.objects.all(), makerspace_id=makerspace.pk,
    ).filter(makerspace=makerspace).first() or MakerspaceBillingSettings(makerspace=makerspace)
    before = policy.reminder_days_before
    after = policy.reminder_days_after
    maximum = policy.max_reminders
    return sorted({*[-day for day in before], 0, *after})[:maximum]


def _steps(makerspace, payment):
    day = to_local(makerspace, payment.due_at).date()
    due = local_day_bounds(makerspace, day)[0]
    offsets = tuple(int((local_day_bounds(makerspace, day + timedelta(days=step))[0] - due)
                        .total_seconds()) for step in _days(makerspace))
    return due, offsets


def _eligible(makerspace):
    from apps.integrations.notification_catalog import is_notification_enabled
    return (module_enabled(makerspace, "email") and
            is_notification_enabled(makerspace, "payments", "email") and
            feature_enabled(makerspace, "billing.reminders"))


def _payments(makerspace):
    return rbac.scope_for_scheduled_work(
        Payment.objects.select_related("makerspace"), makerspace_id=makerspace.pk,
    ).filter(makerspace=makerspace, status=Payment.Status.PENDING, due_at__isnull=False,
             member__isnull=False, member__is_active=True, member__access_status="active")


def discover_payments(makerspace, now, limit, local_tz):
    if not _eligible(makerspace):
        return
    days = _days(makerspace)
    if not days:
        return
    queryset = _payments(makerspace)
    outstanding = Q()
    for index, day in enumerate(days):
        finished = rbac.scope_for_scheduled_work(
            ReminderSchedule.objects.all(), makerspace_id=makerspace.pk,
        ).filter(source="payments.due", subject=Cast(OuterRef("pk"), CharField()),
                 kind=f"day:{day}")
        name = f"step_done_{index}"
        queryset = queryset.annotate(**{name: Exists(finished)})
        outstanding |= Q(**{name: False})
    # Remove fully scheduled subjects BEFORE the limit so later debts cannot starve.
    horizon = to_local(makerspace, now).date() + timedelta(days=max(0, -min(days)) + 1)
    queryset = queryset.filter(outstanding, due_at__lt=local_day_bounds(makerspace, horizon)[0])
    # F1's limit counts reminder identities, not payments. Each yield fits one step;
    # Existing steps are omitted so a small batch can advance through the ladder.
    for payment in queryset.order_by("due_at", "pk")[:limit]:
        due, offsets = _steps(makerspace, payment)
        finished = set(rbac.scope_for_scheduled_work(
            ReminderSchedule.objects.all(), makerspace_id=makerspace.pk,
        ).filter(source="payments.due", subject=str(payment.pk)).values_list("kind", flat=True))
        for day, offset in zip(days, offsets):
            if f"day:{day}" not in finished:
                yield ReminderSubject(str(payment.pk), f"day:{day}", due, (offset,))


def _current_payment(makerspace, reminder, now):
    if not _eligible(makerspace) or not reminder.subject.isdecimal():
        return None
    payment = _payments(makerspace).filter(pk=int(reminder.subject)).first()
    if payment is None:
        return None
    due, offsets = _steps(makerspace, payment)
    if reminder.due_at != due or reminder.offset_seconds not in offsets:
        return None
    day = (to_local(makerspace, reminder.remind_at).date() - to_local(makerspace, due).date()).days
    if reminder.kind != f"day:{day}":
        return None
    # A missed due-day message must not say "due today" several days later.
    # Overdue steps can catch up; advance notices expire with their scheduled day.
    if reminder.offset_seconds <= 0 and (
        to_local(makerspace, now).date() != to_local(makerspace, reminder.remind_at).date()
    ):
        return None
    # After downtime send only the latest eligible step, avoiding a catch-up storm.
    elapsed = [offset for offset in offsets if due + timedelta(seconds=offset) <= now]
    if not elapsed or reminder.offset_seconds != max(elapsed):
        return None
    return payment


def build_payment_message(makerspace, reminder, now, local_tz):
    if _current_payment(makerspace, reminder, now) is None:
        return None
    event = ("payment_due_soon" if reminder.offset_seconds < 0 else
             "payment_due_today" if reminder.offset_seconds == 0 else "payment_overdue")
    return ReminderMessage(title="Payment reminder", event=event)


def dispatch_payment_message(makerspace, reminder, message, now, local_tz):
    payment = _current_payment(makerspace, reminder, now)
    if payment is not None:
        from apps.payments.notifications import notify_payment
        notify_payment(payment, message.event, requester_only=True)
