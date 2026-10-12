"""B10 booking reminders, with current status/tenant/member revalidation."""

from datetime import timedelta

from django.utils import timezone

from apps.accounts import rbac
from apps.integrations.notify import NotificationResult
from apps.bookings.models import Booking
from apps.bookings.notifications import _effective_toggle
from apps.integrations.email_templates_fablab import bookings_context
from apps.makerspaces.reminder_policy import reminder_offsets
from apps.makerspaces.platform import module_enabled
from apps.operations.reminder_members import (
    dispatch_member_reminder, occurrence_subject, recipient_member, unfinished_subjects,
)
from apps.operations.reminder_types import ReminderMessage, ReminderSource, ReminderSubject

SOURCE_KEY = "bookings.booking"


def _bookings(makerspace):
    return rbac.scope_for_scheduled_work(
        Booking.objects.all(), makerspace_id=makerspace.pk, field="space__makerspace_id",
    ).filter(status=Booking.Status.CONFIRMED, member__isnull=False).select_related("space__makerspace")


def discover_booking_reminders(makerspace, now, limit, local_tz):
    if not module_enabled(makerspace, 'membership'):
        return
    offsets = reminder_offsets(makerspace, "booking")
    if not offsets:
        return
    rows = unfinished_subjects(_bookings(makerspace), makerspace, SOURCE_KEY, offsets, now=now)
    rows = rows.filter(starts_at__gt=now, starts_at__lte=now + timedelta(seconds=-min(offsets)))
    for row in rows.order_by("starts_at", "pk")[:limit]:
        yield ReminderSubject(occurrence_subject(row.pk, row.starts_at), "starts", row.starts_at, offsets)


def _eligible(makerspace, schedule, now):
    if schedule.kind != "starts" or schedule.offset_seconds not in reminder_offsets(makerspace, "booking"):
        return None
    subject_id = schedule.subject.split(":", 1)[0]
    if not subject_id.isdecimal():
        return None
    row = _bookings(makerspace).filter(pk=int(subject_id)).first()
    if (row is None or row.starts_at != schedule.due_at or row.starts_at <= now
            or not _effective_toggle(row)
            or recipient_member(makerspace, row.member_id, "bookings") is None):
        return None
    return row


def build_booking_reminder(makerspace, schedule, now, local_tz):
    row = _eligible(makerspace, schedule, now)
    if row is None:
        return None
    return ReminderMessage(title=row.space.name, event="bookings.reminder")


def dispatch_booking_reminder(makerspace, schedule, message, now, local_tz):
    row = _eligible(makerspace, schedule, timezone.now())
    if row is None:
        return NotificationResult(False)
    member = recipient_member(makerspace, row.member_id, "bookings")
    if member is None:
        return NotificationResult(False)
    with timezone.override(makerspace.timezone):
        context = bookings_context(row, "reminder", next_steps="Your booking is coming up.")
    return dispatch_member_reminder(
        makerspace, feature="bookings", member=member, context=context,
        data={"booking_id": row.pk, "space_id": row.space_id},
    )


BOOKING_REMINDER_SOURCE = ReminderSource(
    key=SOURCE_KEY, module="bookings", discover=discover_booking_reminders,
    build=build_booking_reminder, dispatch=dispatch_booking_reminder,
)
