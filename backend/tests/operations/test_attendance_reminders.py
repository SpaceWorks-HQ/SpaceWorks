from datetime import datetime, timedelta, timezone as dt_timezone
from zoneinfo import ZoneInfo

import pytest
from django.utils import timezone
from icalendar import Calendar

from apps.bookings.models import BookableSpace, Booking
from apps.bookings.reminders import BOOKING_REMINDER_SOURCE
from apps.events.models import Event, EventRegistration
from apps.events.reminders import EVENT_REMINDER_SOURCE
from apps.events.services_calendar import render_member_calendar
from apps.integrations.models import EmailLog, NotificationPreference
from apps.integrations.models_recipients import NotificationRecipient
from apps.makerspaces.models import MakerspaceMembership
from apps.makerspaces.reminder_policy import validate_reminder_lead_hours
from apps.operations import reminder_registry, reminder_sweeper
from apps.operations.models import ReminderSchedule
from apps.operations.reminder_services import schedule_reminders
from tests.events.checkin_helpers import make_event, make_member, make_space, register
from tests.module_helpers import disable_module

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture(params=["events", "bookings"])
def attendance(request, monkeypatch, settings):
    domain = request.param
    source = EVENT_REMINDER_SOURCE if domain == "events" else BOOKING_REMINDER_SOURCE
    monkeypatch.setattr(reminder_registry, "REMINDER_SOURCES", (source,))
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    now = timezone.now()
    space = make_space(f"reminder-{domain}")
    space.booking_requester_notifications_enabled = True
    space.save(update_fields=["booking_requester_notifications_enabled"])
    NotificationPreference.objects.create(makerspace=space, feature=domain, channel="email", enabled=True)
    member = make_member(space)
    start = now + timedelta(hours=23)
    if domain == "events":
        row = register(make_event(space, starts_at=start), member)
    else:
        room = BookableSpace.objects.create(makerspace=space, name="Meeting room")
        row = Booking.objects.create(space=room, member=member, name="Member",
                                     email="supplied-contact@example.test", phone="123",
                                     starts_at=start, ends_at=start + timedelta(hours=1),
                                     status=Booking.Status.CONFIRMED)
    return space, member, row, source, now, domain


def _schedules(space):
    return ReminderSchedule.objects.filter(makerspace=space)


def test_reminders_email_only_the_owning_member_once(attendance, mailoutbox, monkeypatch):
    space, member, row, source, now, domain = attendance
    from apps.integrations import notify

    chats = []
    monkeypatch.setattr(notify, "dispatch_channel", lambda **kwargs: chats.append(kwargs))
    assert reminder_sweeper.run_reminder_sweep(now=now)["dispatched"] == 1
    assert reminder_sweeper.run_reminder_sweep(now=now)["dispatched"] == 0
    assert len(mailoutbox) == 1
    assert mailoutbox[0].to == [member.email]
    assert chats == []
    assert _schedules(space).get().state == ReminderSchedule.State.COMPLETED
    assert EmailLog.objects.get(makerspace=space, stream=domain, event="reminder").audience == "requester"


def test_batch_discovery_does_not_starve_the_next_member(attendance):
    space, member, row, source, now, domain = attendance
    another = make_member(space, "another")
    if domain == "events":
        register(row.event, another)
    else:
        Booking.objects.create(space=row.space, member=another, name="Another", email=another.email,
                               phone="123", starts_at=row.starts_at, ends_at=row.ends_at,
                               status=Booking.Status.CONFIRMED)
    assert reminder_sweeper.run_reminder_sweep(now=now, limit=1)["dispatched"] == 1
    assert reminder_sweeper.run_reminder_sweep(now=now, limit=1)["dispatched"] == 1
    assert reminder_sweeper.run_reminder_sweep(now=now, limit=1)["dispatched"] == 0


def test_completed_old_start_does_not_block_one_reminder_for_rescheduled_start(attendance, mailoutbox):
    space, member, row, source, now, domain = attendance
    assert reminder_sweeper.run_reminder_sweep(now=now)["dispatched"] == 1
    if domain == "events":
        row.event.starts_at += timedelta(minutes=5)
        row.event.ends_at += timedelta(minutes=5)
        row.event.save(update_fields=["starts_at", "ends_at"])
    else:
        row.starts_at += timedelta(minutes=5)
        row.ends_at += timedelta(minutes=5)
        row.save(update_fields=["starts_at", "ends_at"])
    assert reminder_sweeper.run_reminder_sweep(now=now)["dispatched"] == 1
    assert reminder_sweeper.run_reminder_sweep(now=now)["dispatched"] == 0
    assert len(mailoutbox) == 2
    assert _schedules(space).count() == 2
    assert len(set(_schedules(space).values_list("subject", flat=True))) == 2


def test_domain_module_off_skips_discovery(attendance, mailoutbox):
    space, member, row, source, now, domain = attendance
    disable_module(space, domain)
    assert reminder_sweeper.run_reminder_sweep(now=now)["dispatched"] == 0
    assert not mailoutbox and not _schedules(space).exists()


def test_unconfirmed_or_rejected_attendance_never_receives_a_reminder(attendance, mailoutbox):
    space, member, row, source, now, domain = attendance
    statuses = (["pending_approval", "waitlisted", "rejected", "attended"]
                if domain == "events" else ["pending", "rejected", "completed", "no_show"])
    for status in statuses:
        row.status = status
        row.save(update_fields=["status"])
        assert reminder_sweeper.run_reminder_sweep(now=now)["dispatched"] == 0
    assert not mailoutbox and not _schedules(space).exists()


def test_booking_requester_email_override_can_suppress_reminders(attendance, mailoutbox):
    space, member, row, source, now, domain = attendance
    if domain != "bookings":
        return
    row.space.requester_notifications_enabled = False
    row.space.save(update_fields=["requester_notifications_enabled"])
    assert reminder_sweeper.run_reminder_sweep(now=now)["dispatched"] == 0
    assert not mailoutbox


def test_cancelled_and_rescheduled_subjects_are_suppressed(attendance, mailoutbox):
    space, member, row, source, now, domain = attendance
    due = row.event.starts_at if domain == "events" else row.starts_at
    schedule, = schedule_reminders(makerspace=space, source=source.key, subject=str(row.pk),
                                  kind="starts", due_at=due, offsets=(-86400,))
    row.status = "cancelled"
    row.save(update_fields=["status"])
    assert reminder_sweeper.run_reminder_sweep(now=now)["dispatched"] == 0
    assert not mailoutbox
    assert source.build(space, schedule, now, ZoneInfo("UTC")) is None
    row.status = "registered" if domain == "events" else "confirmed"
    row.save(update_fields=["status"])
    if domain == "events":
        row.event.starts_at += timedelta(hours=1)
        row.event.ends_at += timedelta(hours=1)
        row.event.save(update_fields=["starts_at", "ends_at"])
    else:
        row.starts_at += timedelta(hours=1)
        row.ends_at += timedelta(hours=1)
        row.save(update_fields=["starts_at", "ends_at"])
    assert source.build(space, schedule, now, ZoneInfo("UTC")) is None


@pytest.mark.parametrize("module", ["notifications", "email", "membership"])
def test_module_off_never_sends_attendance_mail(attendance, module, mailoutbox):
    space, member, row, source, now, domain = attendance
    disable_module(space, module)
    reminder_sweeper.run_reminder_sweep(now=now)
    assert not mailoutbox
    if module != "email":
        assert not _schedules(space).exists()
    else:
        assert EmailLog.objects.get(makerspace=space, event="reminder").status == EmailLog.Status.SKIPPED


@pytest.mark.parametrize("restriction", ["revoked", "opt_out", "suspended", "matrix_off", "recipient_off"])
def test_current_member_and_matrix_preferences_suppress_delivery(attendance, restriction, mailoutbox):
    space, member, row, source, now, domain = attendance
    if restriction in {"revoked", "opt_out"}:
        membership = MakerspaceMembership.objects.get(makerspace=space, user=member)
        if restriction == "revoked":
            membership.status = "revoked"
            membership.save(update_fields=["status"])
        else:
            membership.receives_notifications = False
            membership.save(update_fields=["receives_notifications"])
    elif restriction == "suspended":
        member.access_status = "suspended"
        member.save(update_fields=["access_status"])
    elif restriction == "matrix_off":
        NotificationPreference.objects.filter(makerspace=space, feature=domain).update(enabled=False)
    else:
        NotificationRecipient.objects.create(makerspace=space, feature=domain, event="reminder", kind="members")
    reminder_sweeper.run_reminder_sweep(now=now)
    assert not mailoutbox


def test_foreign_schedule_subject_is_refused(attendance):
    space, member, row, source, now, domain = attendance
    other = make_space("foreign-reminder-tenant")
    due = row.event.starts_at if domain == "events" else row.starts_at
    schedule, = schedule_reminders(makerspace=other, source=source.key, subject=str(row.pk),
                                  kind="starts", due_at=due, offsets=(-86400,))
    assert source.build(other, schedule, now, ZoneInfo("UTC")) is None


def test_due_instants_and_rendering_use_makerspace_zone_across_dst(attendance, mailoutbox, monkeypatch):
    space, member, row, source, _, domain = attendance
    space.timezone = "America/New_York"
    space.save(update_fields=["timezone"])
    start = datetime(2027, 3, 14, 13, tzinfo=dt_timezone.utc)  # 09:00 after DST starts
    now = start - timedelta(hours=24)
    monkeypatch.setattr(timezone, "now", lambda: now)
    if domain == "events":
        row.event.starts_at, row.event.ends_at = start, start + timedelta(hours=1)
        row.event.save(update_fields=["starts_at", "ends_at"])
    else:
        row.starts_at, row.ends_at = start, start + timedelta(hours=1)
        row.save(update_fields=["starts_at", "ends_at"])
    assert reminder_sweeper.run_reminder_sweep(now=now)["dispatched"] == 1
    schedule = _schedules(space).get()
    assert schedule.remind_at == now and schedule.due_at == start
    assert len(mailoutbox) == 1
    assert "9 a.m." in mailoutbox[0].body or "9:00" in mailoutbox[0].body


def test_removed_offsets_and_empty_policy_suppress_pending_steps(attendance, mailoutbox):
    space, member, row, source, now, domain = attendance
    due = row.event.starts_at if domain == "events" else row.starts_at
    schedule_reminders(makerspace=space, source=source.key, subject=str(row.pk),
                       kind="starts", due_at=due, offsets=(-86400,))
    field = "event_reminder_lead_hours" if domain == "events" else "booking_reminder_lead_hours"
    setattr(space, field, [])
    space.save(update_fields=[field])
    assert reminder_sweeper.run_reminder_sweep(now=now)["dispatched"] == 0
    assert _schedules(space).get().state == ReminderSchedule.State.COMPLETED
    assert not mailoutbox


def test_member_calendar_alarms_apply_only_to_confirmed_live_registrations():
    space = make_space("reminder-calendar")
    member = make_member(space)
    space.event_reminder_lead_hours = [24, 2]
    space.save(update_fields=["event_reminder_lead_hours"])
    active = register(make_event(space, title="Active"), member)
    register(make_event(space, title="Cancelled"), member, status="cancelled")
    payload = render_member_calendar(space, EventRegistration.objects.filter(member=member))
    events = Calendar.from_ical(payload).walk("VEVENT")
    confirmed = next(component for component in events if str(component["summary"]) == active.event.title)
    cancelled = next(component for component in events if str(component["summary"]) == "Cancelled")
    assert [alarm.decoded("trigger") for alarm in confirmed.walk("VALARM")] == [timedelta(hours=-24), timedelta(hours=-2)]
    assert not cancelled.walk("VALARM")


@pytest.mark.parametrize("value", [[0], [-1], [24, 24], [True], [1.5], [8761], "24"])
def test_invalid_lead_policy_is_refused(value):
    from django.core.exceptions import ValidationError

    with pytest.raises(ValidationError):
        validate_reminder_lead_hours(value)
