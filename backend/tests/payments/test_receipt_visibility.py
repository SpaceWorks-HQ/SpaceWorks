"""Receipts reach the people who need them: staff see how money arrived, payers see refunds."""

from decimal import Decimal

import pytest

from apps.makerspaces.models import MakerspaceMembership
from apps.payments.models import Payment, Refund
from apps.payments.reconciliation import mark_offline
from tests.payments.test_refunds import paid_deposit, stripe_space
from tests.return_helpers import (
    authenticated_client,
    make_member,
    make_space,
    settlement_details,
    settlement_payload,
)

pytestmark = pytest.mark.django_db


def _dues(space, member):
    return Payment.objects.create(
        makerspace=space,
        subject_type=Payment.SubjectType.MAKERSPACE_MEMBERSHIP,
        subject_id=MakerspaceMembership.objects.get(makerspace=space, user=member).pk,
        member=member,
        amount=Decimal("8.00"),
        currency="usd",
        created_by=member,
    )


def test_the_staff_list_shows_the_standing_receipt_and_whether_it_was_corrected():
    space = make_space("receipt-staff")
    manager = make_member("receipt-staff-manager", space)
    settled = _dues(space, manager)
    pending = _dues(space, make_member("receipt-staff-other", space))
    mark_offline(settled, manager, settlement_details(method="upi", reference="UPI-77"))
    client = authenticated_client(manager)
    url = f"/api/v1/admin/makerspace/{space.pk}/payments"

    before = {row["id"]: row for row in client.get(url).data}
    client.post(
        f"{url}/{settled.pk}/amend-settlement",
        settlement_payload(method="cash", reference="till-2"), format="json",
    )
    after = {row["id"]: row for row in client.get(url).data}

    assert before[settled.pk]["settlement"]["method"] == "upi"
    assert before[settled.pk]["settlement"]["reference"] == "UPI-77"
    assert before[settled.pk]["settlement"]["corrected"] is False
    assert after[settled.pk]["settlement"]["method"] == "cash"
    assert after[settled.pk]["settlement"]["corrected"] is True
    assert after[pending.pk]["settlement"] is None


def test_the_payer_sees_refunds_on_their_own_receipt(monkeypatch):
    makerspace, staff = stripe_space(
        "receipt-member-refund", monkeypatch, [{"id": "re_seen", "status": "succeeded"}]
    )
    payment = paid_deposit(makerspace, staff, amount="10.00")
    authenticated_client(staff).post(
        f"/api/v1/admin/makerspace/{makerspace.pk}/payments/{payment.pk}/refund",
        {"amount": "4.00", "reason": "returned early"}, format="json",
    )
    Refund.objects.create(
        payment=payment, amount=Decimal("1.00"), currency="usd", provider=payment.provider,
        created_by=staff, status=Refund.Status.FAILED,
    )
    borrower = payment.member

    response = authenticated_client(borrower).get(
        f"/api/v1/member/makerspaces/{makerspace.pk}/payments"
    )

    assert response.status_code == 200, response.data
    row = next(item for item in response.data if item["id"] == payment.pk)
    assert Decimal(row["refunded_amount"]) == Decimal("4.00")
    assert sorted(item["status"] for item in row["refunds"]) == ["failed", "succeeded"]
    succeeded = next(item for item in row["refunds"] if item["status"] == "succeeded")
    assert succeeded["reason"] == "returned early"
    assert "created_by" not in succeeded
