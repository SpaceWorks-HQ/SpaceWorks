"""Manual money in/out by method. Effective receipts, actual transfer dates."""

from decimal import Decimal

from apps.operations.report_registry import ReportResult
from apps.operations.report_scope import scoped_ids
from apps.payments.models import ManualSettlement, Refund

FIELDS = ("currency", "method", "collected_amount", "refunded_amount", "net_amount")


def build_payment_cash_book(makerspace_id, *, limit=None, date_range=None):
    ids = scoped_ids(makerspace_id)
    receipts = ManualSettlement.objects.filter(payment__makerspace_id__in=ids, amended_by__isnull=True)
    refunds = Refund.objects.filter(payment__makerspace_id__in=ids, provider="manual", amended_by__isnull=True)
    if date_range:
        start, end = date_range
        for bound, value in (("gte", start), ("lt", end)):
            if value is not None:
                receipts = receipts.filter(**{f"received_at__{bound}": value})
                refunds = refunds.filter(**{f"refunded_at__{bound}": value})
    groups = {}
    for queryset, column in ((receipts, "collected_amount"), (refunds, "refunded_amount")):
        for row in queryset.values("payment__makerspace_id", "currency", "method", "amount").iterator():
            key = (row["payment__makerspace_id"], row["currency"], row["method"])
            target = groups.setdefault(key, {
                "makerspace_id": key[0], "currency": key[1], "method": key[2],
                "collected_amount": Decimal("0.00"), "refunded_amount": Decimal("0.00"),
            })
            target[column] += row["amount"]
    records = []
    for key in sorted(groups):
        row = groups[key]
        row["net_amount"] = row["collected_amount"] - row["refunded_amount"]
        if makerspace_id is not None:
            row.pop("makerspace_id")
        records.append(row)
    fields = (("makerspace_id",) + FIELDS) if makerspace_id is None else FIELDS
    return ReportResult(fields, records[:limit] if limit is not None else records)
