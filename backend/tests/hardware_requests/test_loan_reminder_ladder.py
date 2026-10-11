from datetime import datetime, timedelta, timezone as datetime_timezone

import pytest
from django.utils import timezone
from zoneinfo import ZoneInfo

from apps.hardware_requests.loan_reminders import build_reminder, discover_borrower
from apps.hardware_requests.models import HardwareRequest
from apps.hardware_requests.services_return_reminders import run_return_reminders
from apps.hardware_requests import workflow
from apps.notifications.models import Notification
from apps.integrations.models import NotificationPreference
from apps.operations.models import ReminderSchedule
from apps.operations.reminder_services import schedule_reminders
from apps.operations.reminder_sweeper import run_reminder_sweep
from tests.hardware_requests.loan_policy_helpers import setup_loan
from tests.return_helpers import make_member, make_space

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture(autouse=True)
def local_mail(settings):
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"


def test_before_due_due_and_overdue_steps_are_idempotent_and_borrower_only(mailoutbox):
    due = timezone.now() + timedelta(days=1)
    space, member, _, _, loan, policy, _ = setup_loan("ladder", due_at=due)
    make_member("ladder-staff", space)
    policy.loan_reminder_offsets_hours = [-24, 0, 24]
    policy.save()
    for index, hour in enumerate([-24, 0, 24], start=1):
        instant = due + timedelta(hours=hour)
        assert run_reminder_sweep(now=instant)["dispatched"] == 1
        assert run_reminder_sweep(now=instant)["dispatched"] == 0
        assert len(mailoutbox) == index
    assert all(message.to == [member.email] for message in mailoutbox)
    assert ReminderSchedule.objects.filter(makerspace=space, state="completed").count() == 3
    assert not Notification.objects.filter(makerspace=space).exists()
    loan.refresh_from_db()
    assert loan.return_reminder_sent_at == due


def test_timezone_rendering_and_elapsed_offsets_across_dst(mailoutbox):
    due = datetime(2026, 11, 1, 6, 30, tzinfo=datetime_timezone.utc)
    space, _, _, _, _, policy, _ = setup_loan("dst-ladder", due_at=due)
    space.timezone = "America/New_York"
    space.save(update_fields=["timezone"])
    policy.loan_reminder_offsets_hours = [-24]
    policy.save()
    assert run_reminder_sweep(now=due - timedelta(hours=24, seconds=1))["dispatched"] == 0
    assert run_reminder_sweep(now=due - timedelta(hours=24))["dispatched"] == 1
    assert "2026-11-01 01:30 EST (-0500)" in mailoutbox[0].body
    row = ReminderSchedule.objects.get(makerspace=space)
    assert row.remind_at == due - timedelta(hours=24)


def test_escalation_emits_f3_staff_event_once_without_borrower_copy(mailoutbox, monkeypatch):
    due = timezone.now() - timedelta(days=3)
    space, member, _, _, _, policy, _ = setup_loan("escalate", due_at=due)
    staff = make_member("escalation-staff", space)
    # This scenario verifies email/inbox delivery; it configures no Telegram destination.
    NotificationPreference.objects.create(makerspace=space, feature="hardware_requests",
                                          channel="telegram", enabled=False)
    policy.loan_reminder_offsets_hours = []
    policy.loan_escalate_overdue_days = 3
    policy.save()
    events = []
    from apps.hardware_requests import loan_reminder_notifications

    original = loan_reminder_notifications.notify_lifecycle
    def notify(*args, **kwargs):
        events.append(kwargs["event"])
        return original(*args, **kwargs)
    monkeypatch.setattr(loan_reminder_notifications, "notify_lifecycle", notify)
    assert run_reminder_sweep(now=due + timedelta(days=3))["dispatched"] == 1
    assert run_reminder_sweep(now=due + timedelta(days=3))["dispatched"] == 0
    assert events == ["overdue_escalated"]
    assert Notification.objects.filter(makerspace=space, event="loan.overdue_escalated").count() == 1
    assert [message.to for message in mailoutbox] == [[staff.email]]
    assert all(member.email not in message.to for message in mailoutbox)


def test_returned_rescheduled_and_removed_steps_are_revalidated(mailoutbox):
    due = timezone.now()
    space, _, _, _, loan, policy, _ = setup_loan("stale-ladder", due_at=due)
    subject = next(iter(discover_borrower(space, due, 20, ZoneInfo("UTC"))))
    row = schedule_reminders(makerspace=space, source="loans.return", subject=subject.subject,
                             kind="borrower", due_at=due)[0]
    policy.loan_reminder_offsets_hours = []
    policy.save()
    assert build_reminder(space, row, due, ZoneInfo("UTC")) is None
    policy.loan_reminder_offsets_hours = [0]
    policy.save()
    loan.return_due_at = due + timedelta(days=1)
    loan.save(update_fields=["return_due_at"])
    assert build_reminder(space, row, due, ZoneInfo("UTC")) is None
    loan.return_due_at, loan.status = due, "returned"
    loan.save(update_fields=["return_due_at", "status"])
    assert run_reminder_sweep(now=due)["dispatched"] == 0
    assert not mailoutbox


def test_renewal_creates_new_occurrence_without_replaying_old_steps(mailoutbox):
    due = timezone.now()
    space, member, _, _, loan, policy, _ = setup_loan("renewed-ladder", due_at=due)
    assert run_reminder_sweep(now=due)["dispatched"] == 1
    renewed = workflow.renew_loan(member, loan)
    assert run_reminder_sweep(now=due)["dispatched"] == 0
    assert run_reminder_sweep(now=renewed.return_due_at)["dispatched"] == 1
    assert len(mailoutbox) == 2
    assert ReminderSchedule.objects.filter(makerspace=space, state="completed").count() == 2


def test_no_policy_keeps_existing_reminder_behavior(mailoutbox):
    due = timezone.now()
    space, member, _, _, loan, policy, _ = setup_loan("legacy-reminder", due_at=due)
    policy.delete()
    assert run_reminder_sweep(now=due)["dispatched"] == 0
    assert run_return_reminders(now=due)["sent"] == 1
    assert run_return_reminders(now=due)["sent"] == 0
    assert len(mailoutbox) == 1 and mailoutbox[0].to == [member.email]


def test_opt_in_does_not_repeat_legacy_zero_step(mailoutbox):
    due = timezone.now()
    space, _, _, _, loan, _, _ = setup_loan("legacy-marker", due_at=due)
    loan.return_reminder_sent_at = due
    loan.save(update_fields=["return_reminder_sent_at"])
    assert run_reminder_sweep(now=due)["dispatched"] == 0
    assert not mailoutbox


def test_completed_older_loans_do_not_starve_later_loans_with_small_batch(mailoutbox):
    due = timezone.now()
    setup_loan("fair-a", due_at=due)
    space, member, _, _, loan, _, _ = setup_loan("fair-b", due_at=due)
    # Two subjects in the same tenant exercise discovery fairness rather than fanout.
    HardwareRequest.objects.create(makerspace=space, requester=member, requester_username=member.username,
                                   requester_contact_email=member.email, return_due_at=due, status="issued")
    assert run_reminder_sweep(now=due, limit=1)["dispatched"] == 2
    assert run_reminder_sweep(now=due, limit=1)["dispatched"] == 1
    assert run_reminder_sweep(now=due, limit=1)["dispatched"] == 0


def test_ladder_never_builds_cross_tenant_subject():
    due = timezone.now()
    space, _, _, _, loan, _, _ = setup_loan("scoped-ladder", due_at=due)
    other = make_space("wrong-ladder")
    from apps.makerspaces.models_loan_policy import MakerspaceLoanPolicy

    MakerspaceLoanPolicy.objects.create(makerspace=other)
    row = ReminderSchedule(makerspace=other, subject=f"{loan.pk}:{due.isoformat()}", kind="borrower",
                           due_at=due, offset_seconds=0)
    assert build_reminder(other, row, due, ZoneInfo("UTC")) is None


def test_unverified_contact_is_not_used_as_borrower_address(mailoutbox):
    due = timezone.now()
    _, _, _, _, loan, _, _ = setup_loan("unverified-ladder", due_at=due)
    loan.requester_contact_email = "someone-else@example.test"
    loan.requester_contact_verified = False
    loan.save(update_fields=["requester_contact_email", "requester_contact_verified"])
    run_reminder_sweep(now=due)
    assert not mailoutbox


@pytest.mark.parametrize("module", ["request_workflow", "notifications"])
def test_source_module_gates_keep_borrower_mail_independent_of_staff_inbox(module, mailoutbox):
    due = timezone.now()
    space, _, _, _, _, _, _ = setup_loan(f"ladder-off-{module}", due_at=due)
    space.enabled_modules = [key for key in space.enabled_modules if key != module]
    space.save(update_fields=["enabled_modules"])
    result = run_reminder_sweep(now=due)
    assert result["dispatched"] == (1 if module == "notifications" else 0)
    assert len(mailoutbox) == (1 if module == "notifications" else 0)


def test_custom_date_template_keeps_datetime_type_and_makerspace_zone(mailoutbox):
    from apps.integrations.models import EmailTemplate

    due = datetime(2026, 11, 1, 6, 30, tzinfo=datetime_timezone.utc)
    space, _, _, _, _, _, _ = setup_loan("custom-ladder", due_at=due)
    space.timezone = "America/New_York"
    space.save(update_fields=["timezone"])
    EmailTemplate.objects.create(makerspace=space, stream="hardware", audience="requester",
                                key="return_reminder", subject="Custom return",
                                text_body='Return at {{ request.return_due_at|date:"Y-m-d H:i T" }}',
                                html_body='<p>{{ request.return_due_at|date:"H:i T" }}</p>')
    assert run_reminder_sweep(now=due)["dispatched"] == 1
    assert "Return at 2026-11-01 01:30 EST" in mailoutbox[0].body
    assert "EST (-0500)" in mailoutbox[0].body


def test_hourly_entry_point_dispatches_policy_ladder_without_legacy_duplicate(mailoutbox):
    due = timezone.now()
    setup_loan("hourly-ladder", due_at=due)
    assert run_return_reminders(now=due)["sent"] == 1
    assert run_return_reminders(now=due)["sent"] == 0
    assert run_reminder_sweep(now=due)["dispatched"] == 0
    assert len(mailoutbox) == 1


def test_future_overdue_step_does_not_starve_newly_due_loan(mailoutbox):
    now = timezone.now()
    space, member, _, _, older, policy, _ = setup_loan("fair-future", due_at=now - timedelta(hours=1))
    policy.loan_reminder_offsets_hours = [0, 24]
    policy.save()
    assert run_reminder_sweep(now=now, limit=1)["dispatched"] == 1
    newer = HardwareRequest.objects.create(makerspace=space, requester=member,
                                          requester_username=member.username, requester_contact_email=member.email,
                                          requester_contact_verified=True, return_due_at=now, status="issued")
    assert run_reminder_sweep(now=now, limit=1)["dispatched"] == 1
    assert ReminderSchedule.objects.filter(subject=f"{newer.pk}:{now.isoformat()}", state="completed").exists()
    assert not ReminderSchedule.objects.filter(subject=f"{older.pk}:{older.return_due_at.isoformat()}",
                                                offset_seconds=86400).exists()
    assert len(mailoutbox) == 2
