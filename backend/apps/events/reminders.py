"""E3 registration reminders on the shared F1 schedule and notification matrix."""

from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

from apps.accounts import rbac
from apps.events.models import Event, EventRegistration
from apps.integrations.email_templates_fablab import events_context
from apps.makerspaces.reminder_policy import reminder_offsets
from apps.makerspaces.platform import module_enabled
from apps.operations.reminder_members import (
    dispatch_member_reminder, occurrence_subject, recipient_member, unfinished_subjects,
)
from apps.operations.reminder_types import ReminderMessage, ReminderSource, ReminderSubject

SOURCE_KEY = "events.registration"


def _registrations(makerspace):
    # Durable registration provenance, rather than today's collaboration, chooses
    # the member's tenant. Legacy rows without provenance belong to the venue.
    rows = rbac.scope_for_scheduled_work(
        EventRegistration.objects.all(), field="event__makerspace_id",
    ).filter(
        Q(registered_via_makerspace=makerspace)
        | Q(registered_via_makerspace__isnull=True, event__makerspace=makerspace),
        status=EventRegistration.Status.REGISTERED, event__status=Event.Status.PUBLISHED,
        member__isnull=False,
    )
    return rows.select_related("event__makerspace")


def discover_event_reminders(makerspace, now, limit, local_tz):
    if not module_enabled(makerspace, 'membership'):
        return
    offsets = reminder_offsets(makerspace, "event")
    if not offsets:
        return
    rows = unfinished_subjects(_registrations(makerspace), makerspace, SOURCE_KEY, offsets,
                              now=now, due_field="event__starts_at")
    rows = rows.filter(event__starts_at__gt=now,
                       event__starts_at__lte=now + timedelta(seconds=-min(offsets)))
    for row in rows.order_by("event__starts_at", "pk")[:limit]:
        yield ReminderSubject(occurrence_subject(row.pk, row.event.starts_at), "starts",
                              row.event.starts_at, offsets)


def _eligible(makerspace, schedule, now):
    if schedule.kind != "starts" or schedule.offset_seconds not in reminder_offsets(makerspace, "event"):
        return None
    subject_id = schedule.subject.split(":", 1)[0]
    if not subject_id.isdecimal():
        return None
    row = _registrations(makerspace).filter(pk=int(subject_id)).first()
    if (row is None or row.event.starts_at != schedule.due_at or row.event.starts_at <= now
            or not module_enabled(row.event.makerspace, "events")
            or recipient_member(makerspace, row.member_id, "events") is None):
        return None
    return row


def build_event_reminder(makerspace, schedule, now, local_tz):
    row = _eligible(makerspace, schedule, now)
    if row is None:
        return None
    return ReminderMessage(title=row.event.title, event="events.reminder")


def dispatch_event_reminder(makerspace, schedule, message):
    # Re-read immediately before delivery; cancellation can happen after discovery.
    row = _eligible(makerspace, schedule, timezone.now())
    if row is None:
        return None
    member = recipient_member(makerspace, row.member_id, "events")
    if member is None:
        return None
    with timezone.override(makerspace.timezone):
        context = events_context(row.event, "reminder", row, next_steps="Your event is coming up.")
    return dispatch_member_reminder(
        makerspace, feature="events", member=member, context=context,
        data={"event_id": row.event_id, "registration_id": row.pk},
    )


EVENT_REMINDER_SOURCE = ReminderSource(
    key=SOURCE_KEY, module="events", discover=discover_event_reminders,
    build=build_event_reminder, dispatch=dispatch_event_reminder,
)
