"""P7 receipts, cash book and return/deposit evidence boundary."""

from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import DatabaseError, transaction
from django.urls import reverse
from django.utils import timezone

from apps.accounts import rbac
from apps.evidence.storage import EvidenceValidationResult
from apps.hardware_requests import workflow
from apps.makerspaces.models import MembershipTerm, MakerspaceMembership
from apps.operations.reports_cash_book import build_payment_cash_book
from apps.operations.reports_payments import build_payment_reconciliation
from apps.payments.models import Payment, Refund
from apps.payments.reconciliation import mark_offline, with_refunds
from apps.payments.services_refunds_offline import amend_offline_refund, record_offline_refund
from apps.tenant_migration.money_digest import money_fingerprint, assert_money_unchanged, MoneyDriftRefused
from tests.makerspaces.test_membership_plans import plan
from tests.payments.test_new_subjects import subjects
from tests.payments.test_offline_refunds import cash_deposit, payload
from tests.payments.test_purged_machine_charge import machine_charge
from tests.rbac_f6_helpers import custom_actor
from tests.return_helpers import (
    authenticated_client, make_issued_request, make_member, make_product,
    make_return_evidence, make_space, return_payload, settlement_details,
)

pytestmark = pytest.mark.django_db


def test_append_amendment_keeps_amount_bounds_and_immutable_history():
    space, staff, payment = cash_deposit("p7-amend")
    first = record_offline_refund(payment, actor=staff, **payload("4.00", reference="wrong"))
    before = money_fingerprint(space.pk)
    capture = type("Capture", (), {"source_makerspace_id": space.pk, "money_fingerprint_sha256": before})()
    replacement = amend_offline_refund(payment, actor=staff, refund_id=first.pk,
                                      receipt=payload(method="upi", reference="correct")["receipt"])
    assert first.pk == replacement.amends_id
    first.refresh_from_db()
    assert first.reference == "wrong" and replacement.reference == "correct"
    assert Refund.counted_total(payment) == Decimal("4.00")
    assert money_fingerprint(space.pk) != before
    with pytest.raises(MoneyDriftRefused):
        assert_money_unchanged(capture)
    record_offline_refund(payment, actor=staff, **payload("6.00"))
    assert with_refunds(Payment.objects.all()).get(pk=payment.pk).refunded_amount == Decimal("10.00")
    assert build_payment_reconciliation(space.pk).records[0]["refunded_amount"] == Decimal("10.00")
    payment.refresh_from_db()
    assert payment.status == "paid_offline" and payment.amount == Decimal("10.00")
    replacement.reference = "rewrite"
    with pytest.raises(ValidationError, match="append-only"):
        replacement.save()
    with pytest.raises(DatabaseError, match="append-only"), transaction.atomic():
        Refund.objects.filter(pk=replacement.pk).update(reference="rewrite")


def test_amendments_cannot_branch_cross_payments_or_change_money():
    _, staff, payment = cash_deposit("p7-invalid-amend")
    original = record_offline_refund(payment, actor=staff, **payload("4.00"))
    values = dict(payment=payment, provider="manual", status="succeeded", currency="usd",
                  method="cash", refunded_at=timezone.now(), settled_at=timezone.now(),
                  created_by=staff, amends=original)
    with pytest.raises(ValidationError, match="same manual refund"):
        Refund.objects.create(amount="5.00", **values)
    # bulk_create bypasses clean(); the PostgreSQL guard must enforce the same rule.
    with pytest.raises(DatabaseError, match="same effective manual refund"), transaction.atomic():
        Refund.objects.bulk_create([Refund(amount="5.00", **values)])
    correction = amend_offline_refund(payment, actor=staff, refund_id=original.pk, receipt=payload()["receipt"])
    client = authenticated_client(staff)
    url = reverse("payment-refund-amend", args=[payment.makerspace_id, payment.pk, original.pk])
    assert client.post(url, {"receipt": payload()["receipt"]}, format="json").status_code == 404
    _, other_staff, other = cash_deposit("p7-other-amend")
    url = reverse("payment-refund-amend", args=[other.makerspace_id, other.pk, correction.pk])
    assert authenticated_client(other_staff).post(url, {"receipt": payload()["receipt"]}, format="json").status_code == 404


def test_cash_book_uses_effective_methods_and_actual_transfer_dates():
    space, staff, payment = cash_deposit("p7-cash-book")
    first = record_offline_refund(payment, actor=staff, **payload("4.00", method="cash"))
    amend_offline_refund(payment, actor=staff, refund_id=first.pk, receipt=payload(method="upi")["receipt"])
    by_method = {row["method"]: row for row in build_payment_cash_book(space.pk).records}
    assert by_method["cash"]["collected_amount"] == Decimal("10.00")
    assert by_method["cash"]["net_amount"] == Decimal("10.00")
    assert by_method["upi"]["refunded_amount"] == Decimal("4.00")
    assert by_method["upi"]["net_amount"] == Decimal("-4.00")


def test_cash_deposit_is_released_after_real_return_with_rail_off(monkeypatch):
    space = make_space("p7-real-return")
    staff = make_member("p7-real-return-staff", space)
    request = make_issued_request(space, staff, [(make_product(space), 1)])
    payment = Payment.objects.create(makerspace=space, member=request.requester, created_by=staff,
                                     subject_type="loan_deposit", subject_id=request.pk, amount="10.00", currency="usd")
    mark_offline(payment, staff, settlement_details())
    space.enabled_modules = []
    space.save(update_fields=["enabled_modules"])
    url = reverse("payment-deposit-release", args=[space.pk, payment.pk])
    client = authenticated_client(staff)
    refused = client.post(url, payload(), format="json")
    assert refused.status_code == 400 and refused.data["code"] == "deposit_not_returned"
    monkeypatch.setattr("apps.evidence.storage.finalize_upload", lambda *args: EvidenceValidationResult(size=123, content_type="image/png"))
    data = return_payload(request, make_return_evidence(space, staff))
    returned = workflow.return_items(staff, request, data["evidence_id"], data["remark"], data["box_code"], data["resolutions"])
    assert returned.status == "returned"
    assert not Refund.objects.filter(payment=payment).exists()
    assert client.post(url, payload(), format="json").status_code == 200
    assert client.post(url, payload(), format="json").status_code == 400
    payment.refresh_from_db()
    assert payment.status == "paid_offline"


@pytest.mark.parametrize("kind", Payment.SubjectType.values)
def test_every_charge_kind_supports_cash_refund_without_rail(kind):
    space = make_space(f"p7-kind-{kind}")
    staff = make_member(f"p7-staff-{kind}", space)
    rows = subjects(space, staff)
    if kind == "machine_service_request":
        payment, _ = machine_charge(space, staff)
    else:
        if kind == "membership_term":
            now = timezone.now()
            membership = MakerspaceMembership.objects.get(makerspace=space, user=staff)
            from datetime import timedelta
            rows[kind] = MembershipTerm.objects.create(membership=membership, plan=plan(space),
                                                       starts_at=now, ends_at=now + timedelta(days=30))
        elif kind in Payment.LOAN_SUBJECT_TYPES:
            rows[kind] = make_issued_request(space, staff, [(make_product(space), 1)])
        subject = rows[kind]
        member = subject.requester if kind in Payment.LOAN_SUBJECT_TYPES else staff
        payment = Payment.objects.create(makerspace=space, member=member, created_by=staff,
                                         subject_type=kind, subject_id=subject.pk, amount="10.00", currency="usd")
    mark_offline(payment, staff, settlement_details())
    space.enabled_modules = []
    space.save(update_fields=["enabled_modules"])
    refund = record_offline_refund(payment, actor=staff, **payload("3.00"))
    assert refund.amount == Decimal("3.00")


def test_refund_requires_record_payment_even_with_subject_authority():
    space, _, payment = cash_deposit("p7-record-action")
    issuer = custom_actor(space, [rbac.Action.ISSUE_REQUEST])
    url = reverse("payment-reconciliation-refund-offline", args=[space.pk, payment.pk])
    assert authenticated_client(issuer).post(url, payload(), format="json").status_code == 404
