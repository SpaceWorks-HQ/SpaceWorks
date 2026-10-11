"""Optional renewals use local days, one debt, grace and durable successor identity."""
from datetime import datetime, timedelta, UTC
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.makerspaces.membership_plan_services import create_term, run_membership_renewals
from apps.makerspaces.membership_renewals import current_terms, grace_end
from apps.makerspaces.membership_renewal_reminders import discover, build
from apps.makerspaces.models import MembershipPlan, MembershipTerm
from apps.operations.reminder_services import schedule_reminders
from apps.payments.models import Payment
from apps.payments.reconciliation import mark_offline
from tests.makerspaces.test_membership_plans import member
from tests.module_helpers import disable_module
from tests.return_helpers import make_member, make_space, settlement_details

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def renewal_setup():
    space = make_space("renewal-auto")
    space.enabled_modules = sorted(set(space.enabled_modules) | {"membership", "member_accounts", "notifications"})
    space.enabled_features = sorted(set(space.enabled_features) | {"membership.auto_renew", "membership.lifecycle_mail", "charges.enabled", "charges.membership"})
    space.timezone = "Asia/Kolkata"
    space.lapsed_members_cannot_borrow = True
    space.save()
    manager = make_member("renewal-manager", space)
    membership = member("renewal-person", space)
    plan = MembershipPlan.objects.create(
        makerspace=space, name="Thirty days", interval="custom_days", custom_days=30,
        amount=Decimal("10.00"), currency="usd", auto_renew=True,
        renewal_open_days=14, renewal_grace_days=3, renewal_retries=2,
        reminder_days_before=[14, 7, 1], reminder_days_after=[1, 2],
    )
    end = datetime(2026, 11, 20, 12, tzinfo=UTC)
    term = create_term(manager, membership, plan, starts_at=end - timedelta(days=30))
    return space, manager, membership, plan, term


def test_renewal_window_uses_makerspace_local_day(renewal_setup):
    _, _, _, _, term = renewal_setup
    before = datetime(2026, 11, 5, 18, 29, tzinfo=UTC)  # Nov 5 locally
    at = datetime(2026, 11, 5, 18, 30, tzinfo=UTC)      # Nov 6 locally
    assert run_membership_renewals(now=before)["charged"] == 0
    assert run_membership_renewals(now=at)["charged"] == 1
    assert run_membership_renewals(now=at)["charged"] == 0
    assert Payment.objects.filter(subject_type="membership_term", subject_id=term.pk).count() == 1


def test_offline_settlement_auto_opens_exactly_one_next_term(renewal_setup):
    _, manager, membership, _, term = renewal_setup
    now = term.ends_at - timedelta(days=7)
    run_membership_renewals(now=now)
    term.refresh_from_db()
    mark_offline(term.renewal_payment, manager, settlement_details())
    assert run_membership_renewals(now=now)["opened"] == 1
    assert run_membership_renewals(now=now)["opened"] == 0
    successor = MembershipTerm.objects.get(renewed_from=term)
    assert successor.starts_at == term.ends_at
    assert successor.membership == membership
    assert AuditLog.objects.filter(action="membership.renewed").count() == 1


@pytest.mark.parametrize("free,tracking", [(True, True), (False, False)])
def test_free_or_no_charge_tracking_renewal_extends_without_a_rail(renewal_setup, free, tracking):
    space, _, _, plan, term = renewal_setup
    if free:
        plan.amount = 0
        plan.save()
    if not tracking:
        space.enabled_features.remove("charges.enabled")
        space.save()
    assert run_membership_renewals(now=term.ends_at - timedelta(days=1))["opened"] == 1
    assert not Payment.objects.filter(subject_type="membership_term", subject_id=term.pk).exists()


def test_grace_protects_borrowing_until_boundary_without_revoking(renewal_setup, monkeypatch):
    from apps.makerspaces.request_access import require_current_term
    from apps.presence.guard import MemberPresenceRequired
    space, _, membership, _, term = renewal_setup
    run_membership_renewals(now=term.ends_at + timedelta(hours=1))
    term.refresh_from_db()
    assert term.status == "active"
    within = term.ends_at + timedelta(days=2)
    monkeypatch.setattr(timezone, "now", lambda: within)
    assert current_terms(membership)
    require_current_term(space, membership)
    boundary = grace_end(term)
    monkeypatch.setattr(timezone, "now", lambda: boundary)
    with pytest.raises(MemberPresenceRequired):
        require_current_term(space, membership)
    run_membership_renewals(now=boundary)
    term.refresh_from_db()
    membership.refresh_from_db()
    assert term.status == "expired" and membership.status == "active"
    assert membership.user.access_status == "active"


def test_prepaid_future_term_is_not_current_before_its_start(renewal_setup):
    _, _, membership, _, term = renewal_setup
    assert current_terms(membership, now=term.starts_at - timedelta(seconds=1)) == []


def test_failed_charge_retries_are_bounded_and_do_not_duplicate_debt(renewal_setup, monkeypatch):
    _, _, _, _, term = renewal_setup
    calls = []
    def unavailable(**kwargs):
        calls.append(kwargs)
        raise RuntimeError("Provider unavailable")
    monkeypatch.setattr("apps.payments.services.create_payment", unavailable)
    now = term.ends_at - timedelta(days=5)
    for offset in range(5):
        run_membership_renewals(now=now + timedelta(days=offset))
    term.refresh_from_db()
    assert len(calls) == 3  # initial attempt + two retry attempts
    assert term.renewal_attempts == 3 and term.renewal_retry_at is None
    assert term.renewal_payment_id is None and term.status == "active"
    assert AuditLog.objects.filter(action="membership.renewal_retry").count() == 3


def test_checkout_failure_keeps_recorded_charge_and_retries_same_payment(renewal_setup, monkeypatch):
    from tests.payments.test_models import configured_settings
    space, _, _, _, term = renewal_setup
    space.enabled_modules = sorted(set(space.enabled_modules) | {"payments"})
    space.enabled_features += ["payments.enabled", "payments.membership"]
    space.save()
    configured_settings(space)
    calls = []
    def unavailable(payment_id, **kwargs):
        calls.append(payment_id)
        raise RuntimeError("Provider unavailable")
    monkeypatch.setattr("apps.payments.services.create_checkout_url", unavailable)
    now = term.ends_at - timedelta(days=5)
    for offset in range(5):
        run_membership_renewals(now=now + timedelta(days=offset))
    assert len(calls) == 3 and len(set(calls)) == 1
    assert Payment.objects.filter(subject_type="membership_term", subject_id=term.pk).count() == 1
    assert list(AuditLog.objects.filter(action="membership.renewal_checkout_attempted",
                    target_id=str(term.pk)).order_by("pk").values_list("meta", flat=True)) == [
        {"attempt": 1}, {"attempt": 2}, {"attempt": 3},
    ]


def test_cancellation_prevents_charging_and_opening(renewal_setup):
    _, _, membership, _, term = renewal_setup
    membership.renewal_cancelled_at = timezone.now()
    membership.save()
    counts = run_membership_renewals(now=term.ends_at - timedelta(days=1))
    assert counts["charged"] == 0 and counts["opened"] == 0
    assert not MembershipTerm.objects.filter(renewed_from=term).exists()


def test_membership_module_off_makes_automation_inert(renewal_setup):
    space, _, _, _, term = renewal_setup
    disable_module(space, "membership")
    counts = run_membership_renewals(now=term.ends_at + timedelta(days=10))
    term.refresh_from_db()
    assert counts["charged"] == 0 and counts["opened"] == 0 and term.status == "active"


def test_local_reminders_are_deduplicated_and_stop_after_cancellation(renewal_setup):
    space, _, membership, _, term = renewal_setup
    now = datetime(2026, 11, 19, 18, 30, tzinfo=UTC)  # expiry local day at midnight
    steps = list(discover(space, now, 100, None))
    midnight = next(step for step in steps if step.kind == "day:0")
    assert midnight.due_at == now
    for step in steps:
        schedule_reminders(makerspace=space, source="membership.renewal", subject=step.subject,
                           kind=step.kind, due_at=step.due_at, offsets=step.offsets)
    assert list(discover(space, now, 100, None)) == []
    from apps.operations.models_reminders import ReminderSchedule
    reminder = ReminderSchedule.objects.get(makerspace=space, source="membership.renewal", kind="day:0")
    assert build(space, reminder, now, None).event == "renewal_due"
    grace = ReminderSchedule.objects.get(makerspace=space, source="membership.renewal", kind="grace_started")
    assert build(space, grace, term.ends_at, None).event == "grace_started"
    membership.renewal_cancelled_at = timezone.now()
    membership.save()
    assert build(space, reminder, now, None) is None


def test_new_term_month_end_preserves_local_time_across_dst(renewal_setup):
    from apps.makerspaces.local_time import to_local
    space, manager, membership, plan, _ = renewal_setup
    space.timezone = "America/New_York"
    space.save()
    plan.interval, plan.custom_days = "monthly", None
    plan.save()
    start = datetime(2026, 10, 15, 16, tzinfo=UTC)
    term = create_term(manager, membership, plan, starts_at=start)
    assert to_local(space, term.ends_at).hour == to_local(space, start).hour == 12
    assert term.ends_at.astimezone(UTC).hour == 17


def test_plan_serializer_rejects_unbounded_timing_and_bad_reminders(renewal_setup):
    from apps.admin_api.serializers_membership_plans import MembershipPlanSerializer
    _, _, _, plan, _ = renewal_setup
    for values in ({"renewal_retries": 4}, {"renewal_grace_days": 366},
                   {"reminder_days_before": [True]}, {"reminder_days_after": [0]}):
        assert not MembershipPlanSerializer(plan, data=values, partial=True).is_valid()


def test_promised_grace_survives_automation_disable(renewal_setup):
    space, _, membership, plan, term = renewal_setup
    run_membership_renewals(now=term.ends_at - timedelta(days=1))
    term.refresh_from_db()
    promised = term.grace_until
    plan.auto_renew = False
    plan.save()
    term.refresh_from_db()
    assert grace_end(term) == promised
    assert current_terms(membership, now=term.ends_at + timedelta(days=1))


def test_grace_promise_is_audited_once(renewal_setup):
    _, _, _, _, term = renewal_setup
    now = term.ends_at - timedelta(days=1)
    run_membership_renewals(now=now)
    run_membership_renewals(now=now)
    assert AuditLog.objects.filter(action="membership.grace_promised", target_id=str(term.pk)).count() == 1


@pytest.mark.parametrize("predecessor_state", ["active", "expired"])
def test_completed_staff_successor_does_not_starve_a_due_member(renewal_setup, predecessor_state):
    _, manager, membership, plan, term = renewal_setup
    now = term.ends_at - timedelta(days=1) if predecessor_state == "active" else term.ends_at + timedelta(days=4)
    run_membership_renewals(now=term.ends_at - timedelta(days=7))
    term.refresh_from_db()
    mark_offline(term.renewal_payment, manager, settlement_details())
    term.status = predecessor_state
    term.save()
    create_term(manager, membership, plan, starts_at=term.ends_at)
    other = member("next-renewal-person", membership.makerspace)
    due = create_term(manager, other, plan, starts_at=now - timedelta(days=25))
    assert run_membership_renewals(now=now, limit=1)["charged"] == 1
    due.refresh_from_db()
    assert due.renewal_payment_id


def test_f1_boundary_is_reused_without_a_second_gate(renewal_setup, monkeypatch):
    from apps.tenant_migration.gate_runtime import _boundary_shared_locks
    space, _, _, _, term = renewal_setup
    def nested_gate(*args, **kwargs):
        raise AssertionError("A second tenant boundary was acquired")
    monkeypatch.setattr("apps.tenant_migration.gate_runtime.fanout_tenant_write", nested_gate)
    token = _boundary_shared_locks.set((space.pk,))
    try:
        assert run_membership_renewals(now=term.ends_at - timedelta(days=1))["charged"] == 1
    finally:
        _boundary_shared_locks.reset(token)


def test_discovery_skips_fully_scheduled_history_with_a_small_budget(renewal_setup):
    space, manager, membership, plan, term = renewal_setup
    now = term.ends_at - timedelta(days=1)
    for step in discover(space, now, 1, None):
        schedule_reminders(makerspace=space, source="membership.renewal", subject=step.subject,
                           kind=step.kind, due_at=step.due_at, offsets=step.offsets)
    other = member("reminder-next-person", space)
    due = create_term(manager, other, plan, starts_at=term.starts_at + timedelta(days=1))
    assert {step.subject for step in discover(space, now, 1, None)} == {str(due.pk)}


def test_worker_loss_recovers_initial_checkout_and_duplicate_callbacks_are_inert(renewal_setup, monkeypatch):
    from apps.makerspaces.membership_renewal_charges import attempt_checkout
    from tests.payments.test_models import configured_settings
    space, _, _, _, term = renewal_setup
    space.enabled_modules = sorted(set(space.enabled_modules) | {"payments"})
    space.enabled_features += ["payments.enabled", "payments.membership"]
    space.save()
    configured_settings(space)
    now = term.ends_at - timedelta(days=5)
    # Simulate death after committing debt, before any on-commit callback executes.
    with monkeypatch.context() as interrupted:
        interrupted.setattr("django.db.transaction.on_commit", lambda *a, **kw: None)
        run_membership_renewals(now=now)
    term.refresh_from_db()
    assert term.renewal_payment_id and term.renewal_retry_at == now
    calls = []
    monkeypatch.setattr("apps.payments.services.create_checkout_url",
                        lambda pk, **kw: calls.append(pk) or "https://pay.example.test/checkout")
    run_membership_renewals(now=now)
    attempt_checkout(term.pk, now)  # A second racing callback sees the completed claim.
    term.refresh_from_db()
    assert calls == [term.renewal_payment_id]
    assert term.renewal_attempts == 1 and term.renewal_retry_at is None
