"""F1 owns coordination; the admission family owns applicant email delivery."""

from dataclasses import replace
from datetime import timedelta
from zoneinfo import ZoneInfo

import pytest
from django.utils import timezone

from apps.makerspaces.models import MembershipRequest
from apps.operations import membership_payment_reminders as source
from apps.operations import reminder_registry, reminder_sweeper
from apps.operations.management.commands.run_scheduled_tasks import SCHEDULED_TASKS
from apps.operations.models_reminders import ReminderSchedule
from apps.operations.reminder_services import schedule_reminders
from apps.operations.tasks_admissions import sweep_membership_admissions_task
from apps.payments.models import Payment
from tests.module_helpers import disable_module
from tests.return_helpers import make_member, make_space, make_user

pytestmark = pytest.mark.django_db(transaction=True)


def waiting_request(space, suffix, now):
    manager = make_member(f"reminder-manager-{suffix}", space)
    applicant = make_user(f"reminder-applicant-{suffix}", access_status="active")
    request = MembershipRequest.objects.create(
        makerspace=space, user=applicant, requested_by=applicant,
        kind="request", state="awaiting_payment", expires_at=now + timedelta(hours=12),
    )
    payment = Payment.objects.create(
        makerspace=space, subject_type="membership_request", subject_id=request.pk,
        member=applicant, amount="12", currency="usd", created_by=manager,
        provider=Payment.Provider.UNCLAIMED,
    )
    request.admission_payment = payment
    request.save(update_fields=["admission_payment"])
    return request, payment


@pytest.fixture(autouse=True)
def use_admission_source(monkeypatch):
    monkeypatch.setattr(reminder_registry, "REMINDER_SOURCES", (source.MEMBERSHIP_PAYMENT_SOURCE,))


def test_payment_reminder_dispatches_applicant_family_once_and_advances_bounded_batch(monkeypatch):
    now = timezone.now()
    space = make_space("admission-reminder-once")
    requests = [waiting_request(space, suffix, now)[0] for suffix in ("first", "second")]
    calls = []
    monkeypatch.setattr(
        "apps.makerspaces.membership_admission_notifications.notify_admission",
        lambda request, event: calls.append((request.pk, event)),
    )
    assert reminder_sweeper.run_reminder_sweep(now=now, limit=1)["dispatched"] == 1
    assert reminder_sweeper.run_reminder_sweep(now=now, limit=1)["dispatched"] == 1
    assert reminder_sweeper.run_reminder_sweep(now=now, limit=1)["dispatched"] == 0
    assert calls == [(request.pk, "payment_due") for request in requests]
    assert ReminderSchedule.objects.filter(state="completed", source=source.SOURCE_KEY).count() == 2


@pytest.mark.parametrize("change", ["settled", "expired", "canceled", "foreign"])
def test_live_payment_reminder_refuses_changed_subject(change):
    now = timezone.now()
    space = make_space("admission-reminder-live")
    request, payment = waiting_request(space, "live", now)
    reminder = schedule_reminders(
        makerspace=space, source=source.SOURCE_KEY, subject=str(request.pk),
        kind="payment_due", due_at=request.expires_at, offsets=(source.OFFSET,),
    )[0]
    if change == "settled":
        payment.status = Payment.Status.WAIVED
        payment.save(update_fields=["status", "updated_at"])
    elif change == "expired":
        MembershipRequest.objects.filter(pk=request.pk).update(expires_at=now - timedelta(seconds=1))
    elif change == "canceled":
        MembershipRequest.objects.filter(pk=request.pk).update(state="canceled")
    else:
        other = make_space("admission-reminder-foreign")
        assert source.build_payment_message(other, reminder, now, ZoneInfo("UTC")) is None
        return
    assert source.build_payment_message(space, reminder, now, ZoneInfo("UTC")) is None


@pytest.mark.parametrize("module", ["membership", "notifications"])
def test_module_off_never_sends_payment_reminder(module, monkeypatch):
    now = timezone.now()
    space = make_space("admission-reminder-gates")
    waiting_request(space, "gates", now)
    disable_module(space, module)
    calls = []
    monkeypatch.setattr(
        "apps.makerspaces.membership_admission_notifications.notify_admission",
        lambda *args: calls.append(args),
    )
    assert reminder_sweeper.run_reminder_sweep(now=now)["dispatched"] == 0
    assert calls == []


def test_custom_dispatch_is_after_fresh_module_check(monkeypatch):
    now = timezone.now()
    space = make_space("admission-reminder-dispatch-gate")
    waiting_request(space, "dispatch-gate", now)
    calls = []
    original_build = source.MEMBERSHIP_PAYMENT_SOURCE.build

    def build_and_disable(makerspace, reminder, at, local_tz):
        message = original_build(makerspace, reminder, at, local_tz)
        disable_module(makerspace, "membership")
        return message

    custom = replace(source.MEMBERSHIP_PAYMENT_SOURCE, build=build_and_disable,
                     dispatch=lambda *args: calls.append(args))
    monkeypatch.setattr(reminder_registry, "REMINDER_SOURCES", (custom,))
    assert reminder_sweeper.run_reminder_sweep(now=now)["dispatched"] == 0
    assert calls == []


def test_admission_sweep_is_registered_and_calls_domain_service(monkeypatch):
    from django.conf import settings
    from apps.tenant_migration.gate_policy_tasks import (
        FANOUT_GATE_PARTICIPANTS, TASK_INTERNAL_PARTICIPANTS,
    )

    path = "apps.operations.tasks_admissions.sweep_membership_admissions_task"
    assert ("membership-admissions", path, 5) in SCHEDULED_TASKS
    assert settings.CELERY_BEAT_SCHEDULE["membership-admissions"]["task"] == path
    assert path in TASK_INTERNAL_PARTICIPANTS
    assert "apps.makerspaces.membership_admission_payments.sweep_admissions" in FANOUT_GATE_PARTICIPANTS
    registered = {item.key: item for item in reminder_registry.registered_sources()}
    assert registered[source.SOURCE_KEY].dispatch == source.dispatch_payment_message
    expected = {"expired": 1, "activated": 2}
    monkeypatch.setattr(
        "apps.makerspaces.membership_admission_payments.sweep_admissions", lambda: expected,
    )
    assert sweep_membership_admissions_task() == expected
