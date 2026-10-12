"""Ledger detail and local-calendar money summaries without cross-currency totals."""

from datetime import timedelta
from decimal import Decimal

from apps.makerspaces.local_time import to_local
from apps.operations.report_types import ReportResult
from apps.operations.reports_finance_sources import finance_sources

LEDGER_FIELDS = ("date", "row_kind", "row_id", "payment_id", "document_number", "subject_type",
                 "payer_type", "payer_id", "status", "currency", "amount", "collected_amount",
                 "owed_amount", "refunded_amount", "method", "reference", "effective", "refund_status")
REVENUE_FIELDS = ("period", "currency", "subject_type", "collected_amount", "owed_amount",
                  "refunded_amount", "waived_amount", "net_amount")
CASH_FIELDS = ("period", "currency", "method", "collected_amount", "refunded_amount", "net_amount")


def _result(fields, records, makerspace_id, limit):
    fields = (("makerspace_id",) + fields) if makerspace_id is None else fields
    return ReportResult(fields, records[:limit] if limit is not None else records,
                        {"money_dates": "manual received/refunded date; online settled timestamp",
                         "legacy_dates": "Payment.updated_at fallback for undocumented historical settlements",
                         "owed": "currently pending charges, allocated to creation date; not a historic balance",
                         "calendar": "makerspace local time; weeks start Monday", "tax": "unused"})


def build_payments_ledger(makerspace_id, *, limit=None, date_range=None, subject_type=None, status=None):
    records = []
    for _, row in finance_sources(makerspace_id, date_range=date_range, subject_type=subject_type, status=status):
        records.append({**{field: "" for field in LEDGER_FIELDS},
                        **{field: Decimal("0.00") for field in ("collected_amount", "owed_amount", "refunded_amount")}, **row})
    records.sort(key=lambda row: (row["date"], row["makerspace_id"], row["row_kind"], row["row_id"]))
    return _result(LEDGER_FIELDS, records, makerspace_id, limit)


def _period(space, at, grain):
    day = to_local(space, at).date()
    if grain == "week":
        day -= timedelta(days=day.weekday())
    elif grain == "month":
        day = day.replace(day=1)
    elif grain != "day":
        raise ValueError("Unsupported finance grain.")
    return day.isoformat()


def _summary(makerspace_id, *, grain, date_range, cash_only=False, subject_type=None, status=None):
    groups = {}
    columns = ("collected_amount", "refunded_amount") if cash_only else (
        "collected_amount", "owed_amount", "refunded_amount", "waived_amount")
    dimension = "method" if cash_only else "subject_type"
    for space, row in finance_sources(makerspace_id, date_range=date_range, subject_type=subject_type, status=status):
        if not row["effective"]:
            continue
        if row["row_kind"] == "refund" and row.get("refund_status") != "succeeded":
            continue
        if cash_only and (row["row_kind"] not in ("manual_settlement", "legacy_settlement", "refund") or
                          row.get("method") not in ("cash", "upi", "bank_transfer", "card_machine", "cheque", "other", "unknown")):
            continue
        period = _period(space, row["date"], grain)
        key = (space.pk, period, row["currency"], row.get(dimension, ""))
        target = groups.setdefault(key, dict(makerspace_id=space.pk, period=period, currency=row["currency"],
                                             **{dimension: key[-1]}, **{column: Decimal("0.00") for column in columns}))
        for column in columns:
            target[column] += row.get(column, 0)
    records = []
    for key in sorted(groups):
        row = groups[key]
        row["net_amount"] = row["collected_amount"] - row["refunded_amount"]
        records.append(row)
    return records


def build_revenue_over_time(makerspace_id, *, limit=None, date_range=None, grain="day", subject_type=None, status=None):
    return _result(REVENUE_FIELDS, _summary(makerspace_id, grain=grain, date_range=date_range,
                   subject_type=subject_type, status=status), makerspace_id, limit)


def build_cash_book(makerspace_id, *, limit=None, date_range=None, grain="day", subject_type=None, status=None):
    return _result(CASH_FIELDS, _summary(makerspace_id, grain=grain, date_range=date_range, cash_only=True,
                   subject_type=subject_type, status=status), makerspace_id, limit)
