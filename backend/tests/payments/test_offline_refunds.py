"""Core offline refunds: scoped receipts, balance, auditing and member visibility."""

from datetime import timedelta
from decimal import Decimal
from unittest.mock import Mock

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.makerspaces.models import MakerspaceMembership
from apps.operations.reports_payments import build_payment_reconciliation
from apps.payments.models import Payment, Refund
from apps.payments.reconciliation import mark_offline
from apps.payments.services_refunds_offline import record_offline_refund
from apps.tenant_migration.money_digest import MoneyDriftRefused, assert_money_unchanged, money_fingerprint
from tests.payments.test_refunds import paid_deposit
from tests.return_helpers import authenticated_client, make_member, make_space, settlement_details

pytestmark = pytest.mark.django_db


def cash_deposit(slug="cash-deposit"):
    space = make_space(slug)
    staff = make_member(f"{slug}-staff", space)
    # A cash deposit never had a card intent; keep it distinct from online fixtures.
    payment = paid_deposit(space, staff, status=Payment.Status.PENDING, intent=f"pi_cash_{slug}")
    mark_offline(payment, staff, settlement_details())
    payment.refresh_from_db()
    # Cash bookkeeping must keep working even after both rails and charge creation stop.
    space.enabled_modules = []
    space.enabled_features = []
    space.save(update_fields=["enabled_modules", "enabled_features", "updated_at"])
    return space, staff, payment


def url(payment, space_id=None):
    return reverse("payment-reconciliation-refund-offline", args=[space_id or payment.makerspace_id, payment.pk])


def payload(amount="4.00", **receipt):
    return {"amount": amount, "reason": "Deposit released", "receipt": {
        "method": "cash", "reference": "", "refunded_at": timezone.now().isoformat(), **receipt,
    }}


def test_cash_deposit_release_without_rail_is_audited_and_payment_stays_unchanged(monkeypatch):
    space, staff, payment = cash_deposit()
    provider = Mock(side_effect=AssertionError("offline refunds must not call a provider"))
    monkeypatch.setattr("apps.payments.services_refunds.get_provider", provider)
    original = Payment.objects.filter(pk=payment.pk).values().get()
    response = authenticated_client(staff).post(url(payment), payload(reference="cash-slip-1"), format="json")

    assert response.status_code == 200
    assert Decimal(response.data["refunded_amount"]) == Decimal("4.00")
    refund = Refund.objects.get(payment=payment)
    assert (refund.provider, refund.status, refund.method, refund.reference) == ("manual", "succeeded", "cash", "cash-slip-1")
    assert refund.created_by == staff and refund.refunded_at and refund.settled_at
    assert Payment.objects.filter(pk=payment.pk).values().get() == original
    audit = AuditLog.objects.get(action="payment.refund_recorded")
    assert audit.actor == staff and audit.makerspace == space
    assert audit.meta == {"payment_id": payment.pk, "refund_id": refund.pk, "amount": "4.00", "method": "cash"}
    provider.assert_not_called()


def test_partial_refunds_allow_the_remainder_and_refuse_any_extra():
    _, staff, payment = cash_deposit("cash-partial")
    client = authenticated_client(staff)
    assert client.post(url(payment), payload("4.00"), format="json").status_code == 200
    over = client.post(url(payment), payload("6.01"), format="json")
    assert over.status_code == 400 and over.data["code"] == "refund_exceeds_balance"
    full = client.post(url(payment), payload("6.00", method="upi", reference="upi-2"), format="json")
    assert full.status_code == 200 and Decimal(full.data["refunded_amount"]) == Decimal("10.00")
    assert client.post(url(payment), payload("0.01"), format="json").status_code == 400
    assert Refund.objects.filter(payment=payment).count() == 2
    assert AuditLog.objects.filter(action="payment.refund_recorded").count() == 2


@pytest.mark.parametrize("change", [
    {"amount": "0"}, {"amount": "-1"}, {"amount": "1.001"}, {"receipt": {}},
    {"receipt": {"method": "invalid", "refunded_at": "2026-01-01T00:00:00Z"}},
    {"receipt": {"method": "cash", "refunded_at": "invalid"}},
    {"receipt": {"method": "cash", "refunded_at": (timezone.now() + timedelta(days=1)).isoformat()}},
    {"receipt": {"method": "cash", "refunded_at": "2026-01-01T00:00:00Z", "reference": "x" * 65}},
])
def test_invalid_receipt_or_amount_writes_nothing(change):
    _, staff, payment = cash_deposit("cash-invalid")
    response = authenticated_client(staff).post(url(payment), {**payload(), **change}, format="json")
    assert response.status_code == 400
    assert not Refund.objects.exists()
    assert not AuditLog.objects.filter(action="payment.refund_recorded").exists()


@pytest.mark.parametrize("status", ["pending", "paid_online", "waived", "canceled"])
def test_only_offline_settled_money_can_be_recorded_as_returned(status):
    space = make_space("cash-wrong-status")
    staff = make_member("cash-wrong-status-staff", space)
    payment = paid_deposit(space, staff, status=status)
    response = authenticated_client(staff).post(url(payment), payload(), format="json")
    assert response.status_code == 400 and response.data["code"] == "refund_not_offline"
    assert not Refund.objects.exists()


def test_scope_subject_authority_and_active_account_are_required():
    space, staff, payment = cash_deposit("cash-auth")
    other = make_space("cash-other")
    other_staff = make_member("cash-other-staff", other)
    # A plain member: a custom membership with no granted actions.
    member = make_member("cash-member", space, membership_role=MakerspaceMembership.Role.CUSTOM)
    assert authenticated_client(other_staff).post(url(payment), payload(), format="json").status_code == 404
    assert authenticated_client(staff).post(url(payment, other.pk), payload(), format="json").status_code == 404
    assert authenticated_client(member).post(url(payment), payload(), format="json").status_code in {403, 404}
    staff.access_status = "suspended"
    staff.save(update_fields=["access_status"])
    assert authenticated_client(staff).post(url(payment), payload(), format="json").status_code == 403
    assert not Refund.objects.exists()


def test_audit_failure_rolls_back_the_refund(monkeypatch):
    _, staff, payment = cash_deposit("cash-rollback")
    monkeypatch.setattr("apps.payments.services_refunds_offline.audit.record", Mock(side_effect=RuntimeError("audit failed")))
    with pytest.raises(RuntimeError):
        record_offline_refund(payment, actor=staff, **payload())
    assert not Refund.objects.exists()


def test_member_history_and_reconciliation_report_show_refunded_money_without_join_duplication():
    space, staff, payment = cash_deposit("cash-visible")
    record_offline_refund(payment, actor=staff, **payload("2.00"))
    record_offline_refund(payment, actor=staff, **payload("3.00"))
    history = authenticated_client(payment.member).get(reverse("member-payment-history", args=[space.pk]))
    assert history.status_code == 200
    assert len(history.data) == 1 and Decimal(history.data[0]["refunded_amount"]) == Decimal("5.00")
    rows = build_payment_reconciliation(space.pk).records
    assert len(rows) == 1
    assert rows[0]["payment_count"] == 1 and rows[0]["amount_total"] == Decimal("10.00")
    assert rows[0]["refunded_amount"] == Decimal("5.00")
    assert rows[0]["outstanding_amount"] == Decimal("0.00")


def test_refund_after_capture_refuses_publication_and_other_space_does_not_drift():
    space, staff, payment = cash_deposit("cash-drift")
    other = make_space("cash-drift-other")
    capture = type("Capture", (), {"source_makerspace_id": space.pk, "money_fingerprint_sha256": money_fingerprint(space.pk)})()
    other_digest = money_fingerprint(other.pk)
    record_offline_refund(payment, actor=staff, **payload())
    with pytest.raises(MoneyDriftRefused):
        assert_money_unchanged(capture)
    assert money_fingerprint(other.pk) == other_digest
