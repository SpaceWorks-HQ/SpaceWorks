"""The manual-settlement ledger: how money that arrived in person is recorded.

Every rule here was built in 97bb3aab/3b270fae but only ever exercised through helpers that
always pass a valid receipt, so none of the refusals had a test of its own.
"""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import DatabaseError, connection, transaction
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.makerspaces.models import MakerspaceMembership
from apps.payments.models import ManualSettlement, Payment
from apps.payments.reconciliation import mark_offline, reconcile_payments
from tests.return_helpers import (
    authenticated_client,
    make_member,
    make_print_manager,
    make_space,
    settlement_details,
    settlement_payload,
)

pytestmark = pytest.mark.django_db


def _dues(space, member, amount="12.50"):
    membership = MakerspaceMembership.objects.get(makerspace=space, user=member)
    return Payment.objects.create(
        makerspace=space,
        subject_type=Payment.SubjectType.MAKERSPACE_MEMBERSHIP,
        subject_id=membership.pk,
        member=member,
        amount=Decimal(amount),
        currency="usd",
        created_by=member,
    )


def _url(space, payment, action):
    return f"/api/v1/admin/makerspace/{space.pk}/payments/{payment.pk}/{action}"


def _settled(slug):
    space = make_space(slug)
    manager = make_member(f"{slug}-manager", space)
    payment = _dues(space, manager)
    mark_offline(payment, manager, settlement_details(method="upi", reference="UPI-1"))
    payment.refresh_from_db()
    return space, manager, payment


@pytest.mark.parametrize("missing", ["method", "received_at"])
def test_the_api_refuses_a_receipt_without_method_or_received_date(missing):
    space = make_space(f"settle-missing-{missing}")
    manager = make_member(f"settle-missing-{missing}-manager", space)
    payment = _dues(space, manager)
    body = settlement_payload()
    body["settlement"].pop(missing)

    response = authenticated_client(manager).post(
        _url(space, payment, "mark-offline"), body, format="json"
    )

    assert response.status_code == 400
    payment.refresh_from_db()
    assert payment.status == Payment.Status.PENDING
    assert not ManualSettlement.objects.filter(payment=payment).exists()


def test_the_api_refuses_a_bare_mark_offline_with_no_receipt_at_all():
    space = make_space("settle-bare")
    manager = make_member("settle-bare-manager", space)
    payment = _dues(space, manager)

    response = authenticated_client(manager).post(_url(space, payment, "mark-offline"), {}, format="json")

    assert response.status_code == 400
    payment.refresh_from_db()
    assert payment.status == Payment.Status.PENDING


def test_a_receipt_dated_in_the_future_is_refused():
    space = make_space("settle-future")
    manager = make_member("settle-future-manager", space)
    payment = _dues(space, manager)
    future = (timezone.now() + timedelta(hours=2)).isoformat()

    response = authenticated_client(manager).post(
        _url(space, payment, "mark-offline"), settlement_payload(received_at=future), format="json"
    )

    assert response.status_code == 400
    payment.refresh_from_db()
    assert payment.status == Payment.Status.PENDING


def test_the_service_itself_refuses_paid_offline_without_a_receipt():
    """`mark_offline` is exported and called directly, so the rule cannot live in a serializer."""
    space = make_space("settle-service")
    manager = make_member("settle-service-manager", space)
    payment = _dues(space, manager)

    with pytest.raises(ValueError, match="settlement details"):
        reconcile_payments(
            actor=manager, makerspace_id=space.pk, payment_ids=[payment.pk],
            target_status=Payment.Status.PAID_OFFLINE,
        )
    payment.refresh_from_db()
    assert payment.status == Payment.Status.PENDING


def test_the_receipt_takes_its_figure_from_the_payment_and_is_audited():
    space = make_space("settle-figure")
    manager = make_member("settle-figure-manager", space)
    payment = _dues(space, manager, amount="40.00")
    body = settlement_payload(method="bank_transfer", reference="NEFT-9")
    # A client naming its own figure must not move the books away from the ledger.
    body["settlement"].update({"amount": "1.00", "currency": "eur"})

    response = authenticated_client(manager).post(_url(space, payment, "mark-offline"), body, format="json")

    assert response.status_code == 200, response.data
    receipt = ManualSettlement.objects.get(payment=payment)
    assert (receipt.amount, receipt.currency) == (Decimal("40.00"), "usd")
    assert (receipt.method, receipt.reference, receipt.recorded_by) == ("bank_transfer", "NEFT-9", manager)
    entry = AuditLog.objects.get(action="payment.paid_offline", target_id=str(payment.pk))
    assert entry.meta == {"method": "bank_transfer", "settlement_id": receipt.pk}


def test_a_receipt_must_match_the_payment_amount_and_currency():
    space, manager, payment = _settled("settle-mismatch")
    for field, value in (("amount", Decimal("1.00")), ("currency", "eur")):
        row = ManualSettlement(
            payment=payment, method="cash", received_at=timezone.now(),
            amount=payment.amount, currency=payment.currency, recorded_by=manager,
        )
        setattr(row, field, value)
        with pytest.raises(ValidationError):
            row.save()


def test_a_correction_cannot_cross_to_another_payment():
    space, manager, payment = _settled("settle-cross")
    other = make_member("settle-cross-other", space)
    other_payment = _dues(space, other)
    mark_offline(other_payment, manager, settlement_details())
    foreign_receipt = ManualSettlement.objects.get(payment=other_payment)

    with pytest.raises(ValidationError):
        ManualSettlement.objects.create(
            payment=payment, method="cash", received_at=timezone.now(),
            amount=payment.amount, currency=payment.currency, recorded_by=manager,
            amends=foreign_receipt,
        )


def test_a_receipt_is_append_only_in_the_model():
    _space, _manager, payment = _settled("settle-model-append")
    receipt = ManualSettlement.objects.get(payment=payment)
    receipt.reference = "rewritten"
    with pytest.raises(ValidationError):
        receipt.save()
    with pytest.raises(ValidationError):
        receipt.delete()


def test_a_receipt_is_append_only_in_the_database():
    """The trigger is what stops a bulk `.update()` or raw SQL from rewriting the cash book."""
    _space, _manager, payment = _settled("settle-db-append")
    receipt = ManualSettlement.objects.get(payment=payment)
    with pytest.raises(DatabaseError), transaction.atomic():
        ManualSettlement.objects.filter(pk=receipt.pk).update(reference="rewritten")
    with pytest.raises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
        cursor.execute("DELETE FROM payments_manualsettlement WHERE id = %s", [receipt.pk])
    receipt.refresh_from_db()
    assert receipt.reference == "UPI-1"


def test_an_amendment_appends_a_chain_and_the_head_is_the_effective_receipt():
    space, manager, payment = _settled("settle-amend")
    first = ManualSettlement.objects.get(payment=payment)
    client = authenticated_client(manager)

    second = client.post(
        _url(space, payment, "amend-settlement"),
        settlement_payload(method="cash", reference="till-4"), format="json",
    )
    third = client.post(
        _url(space, payment, "amend-settlement"),
        settlement_payload(method="cheque", reference="CHQ-7"), format="json",
    )

    assert second.status_code == 200 and third.status_code == 200
    rows = list(ManualSettlement.objects.filter(payment=payment).order_by("pk"))
    assert [row.method for row in rows] == ["upi", "cash", "cheque"]
    assert rows[1].amends_id == first.pk and rows[2].amends_id == rows[1].pk
    assert ManualSettlement.effective_for(payment) == rows[2]
    first.refresh_from_db()
    assert first.reference == "UPI-1"  # the original stays exactly as it was entered
    payment.refresh_from_db()
    assert payment.status == Payment.Status.PAID_OFFLINE
    entry = AuditLog.objects.filter(action="payment.settlement_amended").order_by("pk").last()
    assert entry.meta == {
        "settlement_id": rows[2].pk, "amends_id": rows[1].pk,
        "method": "cheque", "previous_method": "cash",
    }


@pytest.mark.parametrize("status", [Payment.Status.PENDING, Payment.Status.WAIVED])
def test_only_an_offline_settled_payment_can_have_its_receipt_amended(status):
    space = make_space(f"settle-amend-{status}")
    manager = make_member(f"settle-amend-{status}-manager", space)
    payment = _dues(space, manager)
    if status == Payment.Status.WAIVED:
        reconcile_payments(
            actor=manager, makerspace_id=space.pk, payment_ids=[payment.pk],
            target_status=Payment.Status.WAIVED,
        )

    response = authenticated_client(manager).post(
        _url(space, payment, "amend-settlement"), settlement_payload(), format="json"
    )

    assert response.status_code == 404
    assert not ManualSettlement.objects.filter(payment=payment).exists()


def test_an_amendment_needs_the_subject_authority():
    space, _manager, payment = _settled("settle-amend-authority")
    # Machine authority only: membership dues need MANAGE_MAKERSPACE.
    machinist = make_print_manager("settle-amend-authority-machinist", space)

    response = authenticated_client(machinist).post(
        _url(space, payment, "amend-settlement"), settlement_payload(), format="json"
    )

    assert response.status_code in {403, 404}
    assert ManualSettlement.objects.filter(payment=payment).count() == 1


def test_a_bulk_settlement_writes_one_receipt_per_payment():
    space = make_space("settle-bulk")
    manager = make_member("settle-bulk-manager", space)
    other = make_member("settle-bulk-other", space)
    rows = [_dues(space, manager), _dues(space, other, amount="7.00")]

    response = authenticated_client(manager).post(
        f"/api/v1/admin/makerspace/{space.pk}/payments/bulk/mark-offline",
        {"ids": [row.pk for row in rows], **settlement_payload(method="card_machine")},
        format="json",
    )

    assert response.status_code == 200, response.data
    for row in rows:
        receipt = ManualSettlement.objects.get(payment=row)
        assert (receipt.method, receipt.amount) == ("card_machine", row.amount)


def test_the_member_reads_the_effective_receipt_for_money_paid_at_the_desk():
    space, manager, payment = _settled("settle-member")
    authenticated_client(manager).post(
        _url(space, payment, "amend-settlement"),
        settlement_payload(method="cash", reference="till-1"), format="json",
    )

    response = authenticated_client(manager).get(f"/api/v1/member/makerspaces/{space.pk}/payments")

    assert response.status_code == 200
    row = next(item for item in response.data if item["id"] == payment.pk)
    assert row["status"] == Payment.Status.PAID_OFFLINE
    assert row["settlement"]["method"] == "cash"
    assert row["settlement"]["reference"] == "till-1"
