"""Balanced generic cash-basis journal, from immutable issued documents."""

from decimal import Decimal

from apps.makerspaces.local_time import to_local
from apps.operations.report_scope import scoped_ids
from apps.operations.report_types import ReportResult
from apps.operations.reports_finance_sources import finance_window, in_window
from apps.payments.models import MakerspaceBillingSettings, PaymentDocument
from apps.payments.models_billing import default_account_codes

FIELDS = ("date", "document_number", "kind", "payment_id", "subject_type", "currency",
          "account_code", "debit", "credit", "settlement_method")


def build_accounting_journal(makerspace_id, *, limit=None, date_range=None, subject_type=None, status=None):
    ids = scoped_ids(makerspace_id)
    mappings = {row.makerspace_id: row.account_codes for row in MakerspaceBillingSettings.objects.filter(makerspace_id__in=ids)}
    documents = PaymentDocument.objects.filter(makerspace_id__in=ids).select_related("makerspace", "payment").order_by("money_at", "sequence")
    if subject_type:
        documents = documents.filter(payment__subject_type=subject_type)
    if status:
        documents = documents.filter(payment__status=status)
    records = []
    for doc in documents.iterator(chunk_size=1000):
        if not in_window(doc.money_at, finance_window(doc.makerspace, date_range)):
            continue
        codes = {**default_account_codes(), **mappings.get(doc.makerspace_id, {})}
        subject = doc.payment.subject_type
        income = codes.get(subject, codes["deposit"] if subject == "loan_deposit" else codes["income"])
        cash = codes["online"] if doc.settlement_method in ("stripe", "razorpay") else codes["cash"]
        debit, credit = (cash, income) if doc.kind == "receipt" else (income, cash)
        base = dict(makerspace_id=doc.makerspace_id, date=to_local(doc.makerspace, doc.money_at).date().isoformat(),
                    document_number=doc.number, kind=doc.kind, payment_id=doc.payment_id, subject_type=subject,
                    currency=doc.currency, settlement_method=doc.settlement_method)
        records.extend([{**base, "account_code": debit, "debit": doc.amount, "credit": Decimal("0.00")},
                        {**base, "account_code": credit, "debit": Decimal("0.00"), "credit": doc.amount}])
    fields = (("makerspace_id",) + FIELDS) if makerspace_id is None else FIELDS
    return ReportResult(fields, records[:limit] if limit is not None else records,
                        {"basis": "cash; issued documents only", "tax": "unused"})
