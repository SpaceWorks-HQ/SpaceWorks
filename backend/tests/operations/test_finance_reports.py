"""Money reports reconcile to effective ledger heads, currency and local calendar."""

from datetime import date, datetime, timezone as dt_timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from apps.accounts import rbac
from apps.operations.report_exports import csv_bytes
from apps.operations.report_exports_provenance import build_provenance
from apps.operations.report_registry import report_definition
from apps.operations.report_schedule_services import schedule_inputs
from apps.operations.reports import report_rows
from apps.operations.reports_accounting import build_accounting_journal
from apps.operations.reports_finance import build_cash_book, build_payments_ledger, build_revenue_over_time
from apps.operations.views_report_helpers import date_range_from_dates
from apps.payments.documents import issue_receipt
from apps.payments.models import MakerspaceBillingSettings, Payment, PaymentDocument
from apps.payments.models import Refund
from apps.payments.reconciliation import amend_settlement, mark_offline
from apps.payments.services_refunds_offline import record_offline_refund, amend_offline_refund
from tests.payments.test_refunds import paid_deposit
from tests.rbac_f6_helpers import custom_actor
from tests.return_helpers import authenticated_client, make_space, make_member, settlement_details

pytestmark = pytest.mark.django_db
AT = datetime(2026, 10, 10, 20, 0, tzinfo=dt_timezone.utc)  # Oct 11 in Kolkata.


def cash_payment(space, staff, *, amount="10.00", at=AT):
    # Offline collections have no native intent. The shared helper's pi_1 default
    # would violate the deployment-wide unique key on the second fixture.
    payment = paid_deposit(space, staff, status="pending", amount=amount, intent=None)
    Payment.objects.filter(pk=payment.pk).update(created_at=at)
    mark_offline(payment, staff, settlement_details(received_at=at))
    payment.refresh_from_db()
    return payment


def test_money_totals_match_ledger_after_receipt_and_refund_corrections():
    space = make_space("finance-reconcile")
    staff = make_member("finance-reconcile-staff", space)
    payment = cash_payment(space, staff)
    amend_settlement(actor=staff, makerspace_id=space.pk, payment_id=payment.pk,
                     settlement=settlement_details(method="upi", received_at=AT))
    refund = record_offline_refund(payment, amount="4.00", reason="Returned", actor=staff,
                                  receipt={"method": "cash", "reference": "first", "refunded_at": AT})
    amend_offline_refund(payment, refund_id=refund.pk, actor=staff,
                         receipt={"method": "upi", "reference": "corrected", "refunded_at": AT})
    ledger = build_payments_ledger(space.pk).records
    assert len([row for row in ledger if row["row_kind"] == "manual_settlement"]) == 2
    assert len([row for row in ledger if row["row_kind"] == "refund"]) == 2
    collected = sum(row["collected_amount"] for row in ledger)
    refunded = sum(row["refunded_amount"] for row in ledger)
    assert collected == Decimal("10.00") and refunded == Decimal("4.00")
    revenue = build_revenue_over_time(space.pk).records
    assert sum(row["collected_amount"] for row in revenue) == collected
    assert sum(row["refunded_amount"] for row in revenue) == refunded
    assert sum(row["net_amount"] for row in revenue) == Decimal("6.00")
    cash = build_cash_book(space.pk).records
    assert len(cash) == 1 and cash[0]["method"] == "upi" and cash[0]["net_amount"] == Decimal("6.00")


@pytest.mark.parametrize("grain,expected", [("day", "2026-10-11"), ("week", "2026-10-05"), ("month", "2026-10-01")])
def test_local_calendar_bucketing_and_date_filter(grain, expected):
    space = make_space("finance-local")
    space.timezone = "Asia/Kolkata"
    space.save(update_fields=["timezone"])
    staff = make_member("finance-local-staff", space)
    cash_payment(space, staff)
    window = date_range_from_dates(date(2026, 10, 11), date(2026, 10, 11))
    rows = build_revenue_over_time(space.pk, grain=grain, date_range=window).records
    assert len(rows) == 1 and rows[0]["period"] == expected
    assert rows[0]["collected_amount"] == Decimal("10.00")
    excluded = date_range_from_dates(date(2026, 10, 10), date(2026, 10, 10))
    assert build_revenue_over_time(space.pk, date_range=excluded).records == []


def test_owed_waived_and_online_collected_have_distinct_dates_and_currency():
    space = make_space("finance-events")
    staff = make_member("finance-events-staff", space)
    paid = paid_deposit(space, staff)
    receipt = issue_receipt(paid)
    # Document time is immutable even if terminal metadata updates later.
    Payment.objects.filter(pk=paid.pk).update(updated_at=AT)
    pending = paid_deposit(space, staff, status="pending", intent="pi_owed", amount="5.00")
    Payment.objects.filter(pk=pending.pk).update(currency="inr")
    waived = paid_deposit(space, staff, status="waived", intent="pi_waived", amount="2.00")
    rows = build_revenue_over_time(space.pk).records
    totals = {currency: {
        key: sum(row[key] for row in rows if row["currency"] == currency)
        for key in ("collected_amount", "owed_amount", "waived_amount")
    } for currency in {row["currency"] for row in rows}}
    assert totals["usd"] == {"collected_amount": Decimal("10.00"), "owed_amount": 0, "waived_amount": Decimal("2.00")}
    assert totals["inr"]["owed_amount"] == Decimal("5.00")
    online = next(row for row in build_payments_ledger(space.pk).records if row["row_kind"] == "online_settlement")
    assert online["date"] == receipt.money_at and online["document_number"] == receipt.number


def test_accounting_journal_is_balanced_per_currency_and_uses_deposit_liability_mapping():
    space = make_space("accounting-docs")
    staff = make_member("accounting-docs-staff", space)
    payment = cash_payment(space, staff)
    policy = MakerspaceBillingSettings.objects.get(makerspace=space)
    policy.account_codes = {"loan_deposit": "CUSTOM-DEPOSITS", "cash": "PETTY-CASH"}
    policy.save()
    record_offline_refund(payment, amount="3.00", reason="Return", actor=staff,
                          receipt={"method": "cash", "reference": "r1", "refunded_at": AT})
    records = build_accounting_journal(space.pk).records
    assert len(records) == 4
    assert sum(row["debit"] for row in records) == sum(row["credit"] for row in records) == Decimal("13.00")
    assert {row["account_code"] for row in records} == {"CUSTOM-DEPOSITS", "PETTY-CASH"}
    assert {row["document_number"] for row in records} == set(PaymentDocument.objects.filter(payment=payment).values_list("number", flat=True))
    assert report_definition("accounting-journal").allowed_formats == ("csv",)
    policy.account_codes = {"income": "=DANGER"}
    policy.save()
    # Existing exporter protects all CSV values, including staff-configured codes.
    provenance = build_provenance("accounting-journal", version=1, makerspace_id=space.pk, generated_by="test", filters={})
    assert b"'=DANGER" in csv_bytes([["account_code"], ["=DANGER"]], provenance=provenance)


@pytest.mark.parametrize("key", ["payments-ledger", "revenue-over-time", "cash-book", "accounting-journal"])
def test_registry_header_scoping_view_finance_and_module_off(key):
    space = make_space("finance-api")
    staff = make_member("finance-api-staff", space)
    cash_payment(space, staff)
    foreign = make_space("finance-api-foreign")
    cash_payment(foreign, make_member("finance-foreign-staff", foreign), amount="99.00")
    assert all(row.get("amount", row.get("collected_amount", 0)) != Decimal("99.00") for row in build_payments_ledger(space.pk).records)
    assert tuple(report_rows(key, space.pk)[0]) == report_definition(key).fields
    viewer = custom_actor(space, [rbac.Action.VIEW_FINANCE])
    route = f"/api/v1/admin/makerspace/{space.pk}/analytics/{key}"
    assert authenticated_client(viewer).get(route).status_code == 200
    cashier = custom_actor(space, [rbac.Action.RECORD_PAYMENT], name="cashier")
    assert authenticated_client(cashier).get(route).status_code in (403, 404)
    exporter = f"/api/v1/admin/makerspace/{space.pk}/reports/{key}/export?format=csv"
    response = authenticated_client(viewer).get(exporter)
    assert response.status_code == 200
    assert b"report_key=" + key.encode() in b"".join(response.streaming_content)
    space.enabled_modules = []
    space.save(update_fields=["enabled_modules"])
    assert authenticated_client(viewer).get(route).status_code == 400


def test_finance_schedule_retains_subject_filters_and_instant_window():
    schedule = SimpleNamespace(report_key="revenue-over-time", filters={"window_days": 7, "subject_type": "loan_deposit"})
    window, filters = schedule_inputs(schedule, AT)
    assert window[1] == AT and filters == {"subject_type": "loan_deposit"}


def test_refund_attempts_are_exported_but_only_succeeded_money_is_totalled():
    space = make_space("refund-attempt-report")
    staff = make_member("refund-attempt-report-staff", space)
    payment = paid_deposit(space, staff)
    Refund.objects.create(payment=payment, amount="2.00", currency="usd", provider="stripe", created_by=staff)
    Refund.objects.create(payment=payment, amount="1.00", currency="usd", provider="stripe", status="failed", created_by=staff)
    attempts = [row for row in build_payments_ledger(space.pk).records if row["row_kind"] == "refund"]
    assert {row["refund_status"] for row in attempts} == {"pending", "failed"}
    assert sum(row["refunded_amount"] for row in attempts) == 0
    assert sum(row["refunded_amount"] for row in build_revenue_over_time(space.pk).records) == 0


def test_both_folds_of_a_dst_day_land_in_the_same_local_bucket():
    space = make_space("finance-dst")
    space.timezone = "America/New_York"
    space.save(update_fields=["timezone"])
    staff = make_member("finance-dst-staff", space)
    # Both instants are 01:30 on the fall-back day, one on each side of the fold.
    for hour in (5, 6):
        cash_payment(space, staff, at=datetime(2026, 11, 1, hour, 30, tzinfo=dt_timezone.utc))
    window = date_range_from_dates(date(2026, 11, 1), date(2026, 11, 1))
    rows = build_revenue_over_time(space.pk, date_range=window).records
    assert len(rows) == 1 and rows[0]["period"] == "2026-11-01"
    assert rows[0]["collected_amount"] == Decimal("20.00")


def test_historical_offline_money_without_a_receipt_is_not_dropped():
    space = make_space("finance-legacy")
    staff = make_member("finance-legacy-staff", space)
    paid_deposit(space, staff, status="paid_offline")
    cash = build_cash_book(space.pk).records
    assert len(cash) == 1 and cash[0]["method"] == "unknown"
    assert cash[0]["collected_amount"] == Decimal("10.00")


def test_rolling_window_at_utc_midnight_does_not_shift_to_local_midnight():
    space = make_space("finance-midnight-window")
    space.timezone = "Asia/Kolkata"
    space.save(update_fields=["timezone"])
    staff = make_member("finance-midnight-staff", space)
    end = datetime(2026, 10, 12, tzinfo=dt_timezone.utc)
    # Both are October 12 locally; only the first precedes the exact UTC end.
    cash_payment(space, staff, amount="10.00", at=datetime(2026, 10, 11, 23, tzinfo=dt_timezone.utc))
    cash_payment(space, staff, amount="20.00", at=datetime(2026, 10, 12, 1, tzinfo=dt_timezone.utc))
    schedule = SimpleNamespace(report_key="revenue-over-time", filters={"window_days": 1})
    window, _ = schedule_inputs(schedule, end)
    rows = build_revenue_over_time(space.pk, date_range=window).records
    assert sum(row["collected_amount"] for row in rows) == Decimal("10.00")
    journal = build_accounting_journal(space.pk, date_range=window).records
    assert sum(row["debit"] for row in journal) == Decimal("10.00")
