"""Test-only source demonstrating bounded tenant discovery and live revalidation.

This is deliberately NOT registered in production and does not send booking mail.
It emits a staff inbox notice through the existing fail-safe emit path. Real
consumers own their notification matrix, subject eligibility and policy offsets.
"""

from datetime import timedelta

from django.db.models import CharField
from django.db.models.functions import Cast

from apps.accounts import rbac
from apps.bookings.models import Booking
from apps.operations.models_reminders import ReminderSchedule
from apps.operations.reminder_registry import ReminderMessage, ReminderSource, ReminderSubject


def discover_bookings(makerspace, now, limit, local_tz):
    # Fetch far enough ahead to create the negative-offset steps; do not prefilter
    # past starts, because downtime must not drop an overdue step. Excluding final
    # identities prevents completed subjects from starving later discovery batches.
    final_subjects = rbac.scope_for_scheduled_work(
        ReminderSchedule.objects.all(), makerspace_id=makerspace.pk,
    ).filter(
        makerspace=makerspace, source="test.booking", kind="starts", offset_seconds=0,
    ).exclude(state=ReminderSchedule.State.PENDING).values("subject")
    bookings = rbac.scope_for_scheduled_work(
        Booking.objects.all(), makerspace_id=makerspace.pk, field="space__makerspace_id",
    ).filter(
        space__makerspace=makerspace, status=Booking.Status.CONFIRMED,
        starts_at__lte=now + timedelta(days=3),
    ).annotate(reminder_subject=Cast("pk", CharField())).exclude(
        reminder_subject__in=final_subjects,
    ).order_by("starts_at", "pk")[:limit]
    for booking in bookings:
        yield ReminderSubject(str(booking.pk), "starts", booking.starts_at, (0,))


def build_booking_message(makerspace, reminder, now, local_tz):
    # Never trust a cached subject identity to establish tenant ownership or current
    # eligibility. Return None for cancelled subjects, removed offsets or changed
    # due instants. Claimed skips are terminal too: source policy must use a new
    # occurrence identity if a rescheduled subject needs another reminder.
    if reminder.kind != "starts":
        return None
    booking = rbac.scope_for_scheduled_work(
        Booking.objects.all(), makerspace_id=makerspace.pk, field="space__makerspace_id",
    ).filter(
        pk=reminder.subject, space__makerspace=makerspace,
        status=Booking.Status.CONFIRMED, starts_at=reminder.due_at,
    ).first()
    if booking is None or reminder.offset_seconds != 0:
        return None
    local_start = booking.starts_at.astimezone(local_tz).isoformat()
    return ReminderMessage(title="Example booking reminder", event="example.booking.starts",
                           body=f"Booking #{booking.pk}: {local_start}")


EXAMPLE_SOURCE = ReminderSource(
    key="test.booking", module="bookings", discover=discover_bookings,
    build=build_booking_message,
)
