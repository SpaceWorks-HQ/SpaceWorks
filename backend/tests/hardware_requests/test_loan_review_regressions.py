from contextlib import contextmanager
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.hardware_requests import services_return_reminders
from apps.integrations.notify import NotificationResult
from apps.operations.models import ReminderSchedule
from apps.operations.reminder_sweeper import run_reminder_sweep
from tests.hardware_requests.loan_policy_helpers import setup_loan

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.mark.parametrize("failed", [False, True])
def test_undelivered_zero_step_keeps_legacy_marker_empty_and_claim_permanent(failed, monkeypatch):
    due = timezone.now()
    space, _, _, _, loan, policy, _ = setup_loan(f"unsent-zero-{failed}", due_at=due)
    monkeypatch.setattr(
        "apps.hardware_requests.loan_reminder_notifications.deliver_loan_reminder",
        lambda *args: NotificationResult(False, {}, {"email": 1} if failed else {}),
    )
    result = run_reminder_sweep(now=due)
    assert result["failed"] == int(failed)
    assert result["dispatched"] == int(not failed)
    loan.refresh_from_db()
    assert loan.return_reminder_sent_at is None
    row = ReminderSchedule.objects.get(makerspace=space, source="loans.return")
    assert row.state == ("failed" if failed else "completed")
    assert run_reminder_sweep(now=due)["dispatched"] == 0
    assert ReminderSchedule.objects.filter(makerspace=space).count() == 1
    # Removing the policy must not turn an unsent ladder attempt into proof of
    # legacy delivery. The old reminder path can still send the duty-of-care mail.
    policy.delete()
    monkeypatch.setattr(services_return_reminders.notifications, "notify_return_due", lambda row: True)
    assert services_return_reminders.run_return_reminders(now=due)["sent"] == 1


@pytest.mark.parametrize("change", ["returned", "rescheduled", "policy"])
def test_legacy_reminder_revalidates_after_discovery(change, monkeypatch):
    due = timezone.now()
    space, _, _, _, loan, policy, _ = setup_loan(f"legacy-race-{change}", due_at=due)
    policy.delete()
    original = services_return_reminders.fanout_tenant_write

    @contextmanager
    def change_before_boundary(*args, **kwargs):
        if change == "returned":
            loan.status = "returned"
            loan.save(update_fields=["status"])
        elif change == "rescheduled":
            loan.return_due_at = due + timedelta(days=1)
            loan.save(update_fields=["return_due_at"])
        else:
            # Opt into a disabled ladder while a legacy scan is in flight.
            policy.pk = None
            policy.loan_reminder_offsets_hours = []
            policy.save()
        with original(*args, **kwargs) as proceed:
            yield proceed

    monkeypatch.setattr(services_return_reminders, "fanout_tenant_write", change_before_boundary)
    sent = []
    monkeypatch.setattr(services_return_reminders.notifications, "notify_return_due", lambda row: sent.append(row.pk))
    result = services_return_reminders.run_return_reminders(now=due)
    assert result["sent"] == 0 and result["skipped"] >= 1
    assert sent == []
    loan.refresh_from_db()
    assert loan.return_reminder_sent_at is None


def test_loan_fanout_declarations_match_the_actual_gate_callers():
    from apps.tenant_migration.source_gate_fanout_guards import validate_fanout_gate_coverage

    covered = validate_fanout_gate_coverage()
    assert "apps.hardware_requests.services_return_reminders._run_legacy_return_reminders" in covered
    assert "apps.operations.reminder_sweeper.run_reminder_sweep" in covered
    assert "apps.hardware_requests.services_return_reminders.run_return_reminders" not in covered


def test_borrow_item_limit_excludes_returned_damaged_and_missing_units():
    from rest_framework.exceptions import ValidationError
    from apps.inventory import availability

    space, member, _, _, loan, policy, _ = setup_loan("resolved-unit-limit")
    item = loan.items.get()
    item.requested_quantity = item.accepted_quantity = item.issued_quantity = 4
    item.returned_quantity = item.damaged_quantity = item.missing_quantity = 1
    item.save()
    policy.loan_max_items = 2
    policy.save()
    availability.enforce_borrow_limits(space, member, 1)
    with pytest.raises(ValidationError, match="item_limit"):
        availability.enforce_borrow_limits(space, member, 2)


def test_new_loan_authority_fields_preserve_terms_and_consumed_renewals():
    from apps.tenant_migration.authority_guards import DECLARED_AUTHORITY_FIELDS, validate_authority_registry
    from apps.tenant_migration.tenant_dump_catalog import FIELD_POLICIES
    from apps.tenant_migration.tenant_dump_types import AuthorityDisposition

    edges = {
        ("hardware_requests.HardwareRequest", "renewal_count"),
        ("makerspaces.MembershipPlan", "loan_max_active"),
        ("makerspaces.MembershipPlan", "loan_max_items"),
    }
    for label in ("inventory.Category", "inventory.InventoryProduct"):
        edges.update((label, name) for name in ("loan_days", "max_renewals"))
    edges.update(("makerspaces.MakerspaceLoanPolicy", name) for name in (
        "makerspace", "default_loan_days", "loan_renewal_mode", "loan_max_renewals",
        "loan_renewal_days", "loan_max_active", "loan_max_items",
        "loan_reminder_offsets_hours", "loan_escalate_overdue_days",
    ))
    validate_authority_registry()
    for edge in edges:
        assert FIELD_POLICIES[edge].dispositions == (AuthorityDisposition.PRESERVE,)
        assert edge in DECLARED_AUTHORITY_FIELDS
