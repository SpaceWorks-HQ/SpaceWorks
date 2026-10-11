"""Refund report columns count returned money without multiplying source charges."""

from decimal import Decimal

import pytest

from apps.operations.org_report_aggregate import aggregate_rows
from apps.operations.report_definitions_existing import EXISTING_REPORT_DEFINITIONS
from apps.operations.reports_payments import build_payment_reconciliation
from apps.operations.serializers_reports_payments import PaymentReconciliationReportRowSerializer
from apps.payments.models import Refund
from apps.payments.services_refunds_offline import record_offline_refund
from tests.payments.test_offline_refunds import cash_deposit, payload
from tests.payments.test_refunds import paid_deposit

pytestmark = pytest.mark.django_db


def test_report_counts_online_and_offline_refunds_but_not_failed_attempts():
    space, staff, offline = cash_deposit("cash-report")
    record_offline_refund(offline, actor=staff, **payload("2.00"))
    record_offline_refund(offline, actor=staff, **payload("3.00"))
    online = paid_deposit(space, staff)
    Refund.objects.create(payment=online, amount=Decimal("4.00"), currency="usd",
                          provider="stripe", status="succeeded", created_by=staff)
    Refund.objects.create(payment=online, amount=Decimal("6.00"), currency="usd",
                          provider="stripe", status="failed", created_by=staff)
    rows = build_payment_reconciliation(space.pk).records
    assert len(rows) == 2
    by_status = {row["status"]: row for row in rows}
    assert by_status["paid_offline"]["refunded_amount"] == Decimal("5.00")
    assert by_status["paid_online"]["refunded_amount"] == Decimal("4.00")
    for row in rows:
        assert row["payment_count"] == 1 and row["amount_total"] == Decimal("10.00")
    typed = PaymentReconciliationReportRowSerializer(rows, many=True).data
    assert {row["refunded_amount"] for row in typed} == {"5.00", "4.00"}
    definition = next(row for row in EXISTING_REPORT_DEFINITIONS if row.key == "payment-reconciliation")
    assert definition.version == 4 and "refunded_amount" in definition.fields


def test_organization_refund_totals_remain_separate_per_currency():
    def row(currency, amount, refunded):
        return {"currency": currency, "subject_type": "loan_deposit", "status": "paid_offline",
                "settlement_method": "cash", "payment_count": 1, "amount_total": Decimal(amount),
                "outstanding_amount": Decimal("0.00"), "refunded_amount": Decimal(refunded)}

    totals = aggregate_rows("payment-reconciliation", [
        (1, [row("usd", "10.00", "4.00"), row("inr", "50.00", "20.00")]),
        (2, [row("usd", "15.00", "2.00")]),
    ], limit=100)
    by_currency = {row["currency"]: row for row in totals}
    assert by_currency["usd"]["amount_total"] == Decimal("25.00")
    assert by_currency["usd"]["refunded_amount"] == Decimal("6.00")
    assert by_currency["inr"]["refunded_amount"] == Decimal("20.00")
