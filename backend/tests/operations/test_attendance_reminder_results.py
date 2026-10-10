"""Real SMTP outcomes survive the reminder consumer's fail-safe delivery seam."""

import pytest

from apps.integrations.models import EmailLog, NotificationPreference
from apps.operations.models import ReminderSchedule
from apps.operations.reminder_sweeper import run_reminder_sweep
from tests.operations.test_attendance_reminders import attendance

pytestmark = pytest.mark.django_db(transaction=True)


def test_failed_email_marks_schedule_failed_without_automatic_resend(attendance, monkeypatch, mailoutbox):
    space, member, row, source, now, domain = attendance

    def fail_send(*args, **kwargs):
        raise OSError('SMTP unavailable')

    monkeypatch.setattr('django.core.mail.EmailMultiAlternatives.send', fail_send)
    counts = run_reminder_sweep(now=now)
    assert counts['dispatched'] == 0 and counts['failed'] == 1
    assert ReminderSchedule.objects.get(makerspace=space).state == ReminderSchedule.State.FAILED
    assert EmailLog.objects.get(makerspace=space, event='reminder').status == EmailLog.Status.FAILED
    assert run_reminder_sweep(now=now)['failed'] == 0
    assert EmailLog.objects.filter(makerspace=space, event='reminder').count() == 1
    assert not mailoutbox


def test_matrix_suppression_counts_as_skipped_and_stays_terminal(attendance, mailoutbox):
    space, member, row, source, now, domain = attendance
    NotificationPreference.objects.filter(makerspace=space, feature=domain, channel='email').update(enabled=False)
    counts = run_reminder_sweep(now=now)
    assert counts['dispatched'] == 0 and counts['failed'] == 0 and counts['skipped'] >= 1
    assert ReminderSchedule.objects.get(makerspace=space).state == ReminderSchedule.State.COMPLETED
    assert not mailoutbox


def test_future_second_step_cannot_starve_later_members_first_step(attendance, mailoutbox):
    from apps.bookings.models import Booking
    from tests.events.checkin_helpers import make_member, register

    space, member, row, source, now, domain = attendance
    field = 'event_reminder_lead_hours' if domain == 'events' else 'booking_reminder_lead_hours'
    setattr(space, field, [24, 2])
    space.save(update_fields=[field])
    another = make_member(space, 'next-reminder-member')
    if domain == 'events':
        register(row.event, another)
    else:
        Booking.objects.create(space=row.space, member=another, name='Another', email=another.email,
                               phone='123', starts_at=row.starts_at, ends_at=row.ends_at,
                               status=Booking.Status.CONFIRMED)
    assert run_reminder_sweep(now=now, limit=1)['dispatched'] == 1
    assert run_reminder_sweep(now=now, limit=1)['dispatched'] == 1
    assert run_reminder_sweep(now=now, limit=1)['dispatched'] == 0
    assert len(mailoutbox) == 2
    schedules = ReminderSchedule.objects.filter(makerspace=space)
    assert schedules.filter(state='completed', offset_seconds=-86400).count() == 2
    assert schedules.filter(state='pending', offset_seconds=-7200).count() == 2
