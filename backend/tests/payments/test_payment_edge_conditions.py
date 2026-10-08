"""Conditions the audit found built but never exercised (2026-10-09 payments lane)."""

from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from apps.makerspaces.models import MakerspaceMembership
from apps.makerspaces.module_install import install_module, uninstall_module
from apps.operations.reports_payments import build_payment_reconciliation
from apps.payments.availability import online_payments_enabled
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


def _dues(space, member, **extra):
    membership = MakerspaceMembership.objects.get(makerspace=space, user=member)
    return Payment.objects.create(
        makerspace=space,
        subject_type=Payment.SubjectType.MAKERSPACE_MEMBERSHIP,
        subject_id=membership.pk,
        member=member,
        amount=extra.pop("amount", Decimal("9.00")),
        currency="usd",
        created_by=member,
        **extra,
    )


@pytest.mark.parametrize("amount", [Decimal("0.00"), Decimal("-1.00")])
def test_a_payment_can_never_be_zero_or_negative(amount):
    space = make_space(f"edge-amount-{amount}".replace(".", "-"))
    member = make_member(f"edge-amount-{abs(amount)}-{amount < 0}", space)

    with pytest.raises((ValidationError, IntegrityError)), transaction.atomic():
        _dues(space, member, amount=amount)
    assert not Payment.objects.filter(makerspace=space).exists()


def test_marking_an_already_settled_payment_again_is_a_conflict():
    space = make_space("edge-replay")
    manager = make_member("edge-replay-manager", space)
    payment = _dues(space, manager)
    url = f"/api/v1/admin/makerspace/{space.pk}/payments/{payment.pk}"
    client = authenticated_client(manager)

    first = client.post(f"{url}/mark-offline", settlement_payload(), format="json")
    again = client.post(f"{url}/mark-offline", settlement_payload(), format="json")
    waive = client.post(f"{url}/waive", format="json")

    assert first.status_code == 200
    assert again.status_code == 409 and again.data["code"] == "payment_terminal"
    assert waive.status_code == 409
    payment.refresh_from_db()
    assert payment.status == Payment.Status.PAID_OFFLINE
    assert payment.manual_settlements.count() == 1


def test_a_refund_of_money_already_taken_survives_uninstalling_the_module(monkeypatch):
    """Owner decision D-PAY-1 defaulted: a toggle stops NEW charges, never returning old ones.

    Same reasoning as the webhook settling with the module off -- money that really moved
    must stay reconcilable whatever the capability switches say now.
    """
    makerspace, staff = stripe_space(
        "edge-refund-module-off", monkeypatch, [{"id": "re_off", "status": "succeeded"}]
    )
    payment = paid_deposit(makerspace, staff)
    install_module(makerspace, "payments")
    uninstall_module(makerspace, "payments")
    assert not online_payments_enabled(makerspace, "loans")

    response = authenticated_client(staff).post(
        f"/api/v1/admin/makerspace/{makerspace.pk}/payments/{payment.pk}/refund",
        {"amount": "4.00", "reason": "returned early"},
        format="json",
    )

    assert response.status_code == 200, response.data
    refund = Refund.objects.get(payment=payment)
    assert (refund.status, refund.amount) == (Refund.Status.SUCCEEDED, Decimal("4.00"))


def test_the_report_splits_settled_money_by_how_it_arrived():
    space = make_space("edge-report-method")
    manager = make_member("edge-report-method-manager", space)
    others = [make_member(f"edge-report-method-{index}", space) for index in range(3)]
    cash, upi, online = (_dues(space, member) for member in others)
    mark_offline(cash, manager, settlement_details(method="cash"))
    mark_offline(upi, manager, settlement_details(method="upi"))
    Payment.objects.filter(pk=online.pk).update(status=Payment.Status.PAID_ONLINE)
    _dues(space, manager)  # still pending

    rows = build_payment_reconciliation(space.pk).records

    by_method = {(row["status"], row["settlement_method"]): row for row in rows}
    assert by_method[("paid_offline", "cash")]["payment_count"] == 1
    assert by_method[("paid_offline", "upi")]["payment_count"] == 1
    assert by_method[("paid_online", "stripe")]["payment_count"] == 1
    pending = by_method[("pending", "")]
    assert pending["outstanding_amount"] == Decimal("9.00")
