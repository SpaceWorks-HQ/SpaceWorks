"""Review regressions: audits, correction chains, boundaries and reminder defaults."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.db import DatabaseError, transaction
from django.urls import reverse
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.operations.reports_cash_book import build_payment_cash_book
from apps.payments.models import MakerspaceBillingSettings, Payment, Refund
from apps.payments.reminders import _days
from apps.payments.services_refunds_offline import amend_offline_refund, record_offline_refund
from tests.payments.test_offline_refunds import cash_deposit, payload
from tests.return_helpers import authenticated_client

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("account_only", [True, False])
def test_default_terms_cover_account_only_borrowers_and_hidden_tenant_staff(account_only):
    from apps.hardware_requests.models import HardwareRequest
    from apps.payments.services import create_payment
    from tests.return_helpers import make_space, make_member, make_user
    space = make_space("review-terms-scope")
    if account_only:
        actor = make_user("review-account-borrower", access_status="active")
    else:
        actor = make_member("review-hidden-staff", space)
        space.superadmin_access_enabled = False
        space.save(update_fields=["superadmin_access_enabled"])
    MakerspaceBillingSettings.objects.create(makerspace=space, payment_terms_days=5)
    loan = HardwareRequest.objects.create(makerspace=space, requester=actor, requester_username=actor.username)
    payment = create_payment(makerspace=space, member=actor, created_by=actor,
                             subject_type="loan_deposit", subject_id=loan.pk,
                             amount=Decimal("10.00"), currency="usd")
    from apps.makerspaces.local_time import to_local
    assert (to_local(space, payment.due_at).date() - to_local(space, payment.created_at).date()).days == 5


def test_billing_defaults_and_policy_audit_do_not_rewrite_existing_charges():
    space, staff, payment = cash_deposit("review-policy")
    client = authenticated_client(staff)
    url = reverse("payment-billing-settings", args=[space.pk])
    original = client.get(url)
    assert original.status_code == 200
    assert {key: original.data[key] for key in ("payment_terms_days", "reminder_days_before", "reminder_days_after", "max_reminders")} == {"payment_terms_days": 0, "reminder_days_before": [3],
                             "reminder_days_after": [7], "max_reminders": 2}
    assert MakerspaceBillingSettings.objects.get(makerspace=space).next_document_number == 2
    response = client.patch(url, {"payment_terms_days": 14, "max_reminders": 4}, format="json")
    assert response.status_code == 200
    entry = AuditLog.objects.get(makerspace=space, action="payment.billing_policy_updated")
    assert entry.actor_id == staff.pk
    assert entry.meta["fields"] == ["max_reminders", "payment_terms_days"]
    payment.refresh_from_db()
    assert payment.status == "paid_offline" and payment.due_at is None
    assert _days(space) == [-3, 0, 7]


def test_refund_corrections_append_audited_chain_without_changing_balance():
    space, staff, payment = cash_deposit("review-refund-chain")
    original = record_offline_refund(payment, actor=staff, **payload("4.00", reference="original"))
    first = amend_offline_refund(payment, actor=staff, refund_id=original.pk,
                                receipt=payload(reference="first")["receipt"])
    second = amend_offline_refund(payment, actor=staff, refund_id=first.pk,
                                 receipt=payload(reference="second")["receipt"])
    assert list(Refund.objects.filter(payment=payment).order_by("pk")
                .values_list("reference", flat=True)) == ["original", "first", "second"]
    assert Refund.counted_total(payment) == Decimal("4.00")
    entries = list(AuditLog.objects.filter(makerspace=space, action="payment.refund_amended")
                   .order_by("pk"))
    assert [entry.meta["amends_id"] for entry in entries] == [original.pk, first.pk]
    assert [entry.meta["refund_id"] for entry in entries] == [first.pk, second.pk]
    assert all(entry.actor_id == staff.pk for entry in entries)
    assert AuditLog.objects.filter(makerspace=space, action="payment.refund_recorded").count() == 1
    response = authenticated_client(payment.member).get(reverse("member-payment-history", args=[space.pk]))
    assert response.status_code == 200
    row = next(row for row in response.data if row["id"] == payment.pk)
    assert [refund["reference"] for refund in row["refunds"]] == ["second"]
    assert Decimal(str(row["refunded_amount"])) == Decimal("4.00")


def test_cash_book_dates_follow_corrected_transfer_and_do_not_mix_currency_or_tenant():
    from apps.hardware_requests.models import HardwareRequest
    from apps.payments.reconciliation import mark_offline
    from tests.return_helpers import settlement_details
    space, staff, payment = cash_deposit("review-cash-dates")
    other, other_staff, other_payment = cash_deposit("review-cash-other")
    now = timezone.now()
    old = now - timedelta(days=10)
    loan = HardwareRequest.objects.create(makerspace=space, requester=payment.member,
                                           requester_username=payment.member.username)
    euro = Payment.objects.create(makerspace=space, member=payment.member, created_by=staff,
                                   subject_type="loan_deposit", subject_id=loan.pk,
                                   amount=Decimal("6.00"), currency="eur")
    mark_offline(euro, staff, settlement_details())
    record_offline_refund(euro, actor=staff, **payload("1.00"))
    original = record_offline_refund(payment, actor=staff, **payload("4.00", refunded_at=old.isoformat()))
    record_offline_refund(other_payment, actor=other_staff, **payload("3.00"))
    assert build_payment_cash_book(space.pk, date_range=(old, old + timedelta(days=1))).records[0]["refunded_amount"] == Decimal("4.00")
    amend_offline_refund(payment, actor=staff, refund_id=original.pk, receipt=payload(method="upi")["receipt"])
    assert build_payment_cash_book(space.pk, date_range=(old, old + timedelta(days=1))).records == []
    records = build_payment_cash_book(space.pk, date_range=(now - timedelta(days=1), now + timedelta(days=1))).records
    assert {row["currency"] for row in records} == {"usd", "eur"}
    totals = {currency: sum(row["refunded_amount"] for row in records if row["currency"] == currency)
              for currency in ("usd", "eur")}
    assert totals == {"usd": Decimal("4.00"), "eur": Decimal("1.00")}


def test_raw_refund_amendments_cannot_branch_or_point_at_another_payment():
    _, staff, payment = cash_deposit("review-raw-amend")
    _, _, other = cash_deposit("review-raw-other")
    original = record_offline_refund(payment, actor=staff, **payload("4.00"))
    values = {"amount": original.amount, "currency": original.currency, "provider": "manual",
              "status": "succeeded", "created_by": staff, "amends": original,
              "method": "cash", "refunded_at": timezone.now(), "settled_at": timezone.now()}
    with pytest.raises(DatabaseError), transaction.atomic():
        Refund.objects.bulk_create([Refund(payment=other, **values)])
    amend_offline_refund(payment, actor=staff, refund_id=original.pk, receipt=payload()["receipt"])
    with pytest.raises(DatabaseError), transaction.atomic():
        Refund.objects.bulk_create([Refund(payment=payment, **values)])
    assert Refund.counted_total(payment) == Decimal("4.00")
    with pytest.raises(DatabaseError, match="append-only"), transaction.atomic():
        Refund.objects.filter(pk=original.pk).delete()


def test_refund_amendment_audit_failure_rolls_back_receipt(monkeypatch):
    _, staff, payment = cash_deposit("review-amend-rollback")
    original = record_offline_refund(payment, actor=staff, **payload("4.00"))

    def fail_audit(*args, **kwargs):
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr("apps.payments.services_refunds_offline.audit.record", fail_audit)
    with pytest.raises(RuntimeError, match="audit unavailable"):
        amend_offline_refund(payment, actor=staff, refund_id=original.pk,
                             receipt=payload(reference="must roll back")["receipt"])
    assert Refund.objects.filter(payment=payment).count() == 1
    assert Refund.counted_total(payment) == Decimal("4.00")
