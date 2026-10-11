"""Canonical dated finance rows; effective correction heads carry money once."""

from apps.makerspaces.local_time import local_day_bounds
from apps.makerspaces.models import Makerspace
from apps.operations.report_scope import scoped_ids
from apps.operations.report_date_ranges import CalendarDateRange
from apps.payments.models import ManualSettlement, Payment, PaymentDocument, Refund


def finance_window(space, date_range):
    if not date_range:
        return None, None
    # Report request/schedule parsing supplies calendar midnights. Reinterpret those
    # calendar labels in the tenant zone, rather than filtering local days in UTC.
    start, end = date_range
    def bound(value):
        if value is None:
            return None
        # Rolling schedules supply precise instants, rather than calendar midnights.
        return local_day_bounds(space, value.date())[0] if isinstance(date_range, CalendarDateRange) else value
    return bound(start), bound(end)


def in_window(at, bounds):
    start, end = bounds
    return at is not None and (start is None or at >= start) and (end is None or at < end)


def finance_sources(makerspace_id, *, date_range=None, subject_type=None, status=None):
    ids = scoped_ids(makerspace_id)
    spaces = {space.pk: space for space in Makerspace.objects.filter(pk__in=ids)}
    payments = Payment.objects.filter(makerspace_id__in=ids).order_by("pk")
    if subject_type:
        payments = payments.filter(subject_type=subject_type)
    if status:
        payments = payments.filter(status=status)
    docs = PaymentDocument.objects.filter(payment__in=payments)
    online = {doc.payment_id: doc for doc in docs.filter(kind="receipt", settlement__isnull=True, refund__isnull=True, reverses__isnull=True)}
    settlements = {doc.settlement_id: doc for doc in docs.filter(kind="receipt", settlement__isnull=False)}
    refunds = {doc.refund_id: doc for doc in docs.filter(kind="credit_note", refund__isnull=False)}
    manual_ids = set(ManualSettlement.objects.filter(payment__in=payments).values_list("payment_id", flat=True))
    for payment in payments.iterator(chunk_size=1000):
        space = spaces[payment.makerspace_id]
        bounds = finance_window(space, date_range)
        base = dict(makerspace_id=space.pk, payment_id=payment.pk,
                    subject_type=payment.subject_type, currency=payment.currency,
                    payer_id=payment.member_id, payer_type="member" if payment.member_id else "account_less",
                    status=payment.status)
        if in_window(payment.created_at, bounds):
            yield space, {**base, "date": payment.created_at, "row_kind": "charge", "row_id": payment.pk,
                          "amount": payment.amount, "owed_amount": payment.amount if payment.status == "pending" else 0,
                          "effective": True}
        if payment.status == Payment.Status.PAID_ONLINE:
            doc = online.get(payment.pk)
            at = doc.money_at if doc else payment.updated_at
            if in_window(at, bounds):
                yield space, {**base, "date": at, "row_kind": "online_settlement", "row_id": payment.pk,
                              "amount": payment.amount, "collected_amount": payment.amount,
                              "method": payment.provider, "effective": True, "document_number": doc.number if doc else ""}
        if payment.status == Payment.Status.PAID_OFFLINE and payment.pk not in manual_ids and in_window(payment.updated_at, bounds):
            yield space, {**base, "date": payment.updated_at, "row_kind": "legacy_settlement", "row_id": payment.pk,
                          "amount": payment.amount, "collected_amount": payment.amount,
                          "method": "unknown", "effective": True}
        if payment.status == Payment.Status.WAIVED and in_window(payment.updated_at, bounds):
            yield space, {**base, "date": payment.updated_at, "row_kind": "waiver", "row_id": payment.pk,
                          "amount": payment.amount, "waived_amount": payment.amount, "effective": True}
    # Bulk queries, rather than reading a settlement/refund collection for every charge.
    for model, at_field, kind, documents, column in (
        (ManualSettlement, "received_at", "manual_settlement", settlements, "collected_amount"),
        (Refund, "refunded_at", "refund", refunds, "refunded_amount"),
    ):
        rows = model.objects.filter(payment__in=payments).select_related("payment").order_by("pk")
        rows = rows.prefetch_related("amended_by")
        for source in rows.iterator(chunk_size=1000):
            payment = source.payment
            space = spaces[payment.makerspace_id]
            at = getattr(source, at_field) or source.settled_at or source.created_at
            if not in_window(at, finance_window(space, date_range)):
                continue
            effective = not hasattr(source, "amended_by")
            doc = documents.get(source.pk)
            yield space, dict(makerspace_id=space.pk, payment_id=payment.pk,
                              subject_type=payment.subject_type, currency=source.currency,
                              payer_id=payment.member_id, payer_type="member" if payment.member_id else "account_less",
                              status=payment.status, date=at, row_kind=kind, row_id=source.pk,
                              amount=source.amount, **{column: source.amount if effective and
                                  (model is ManualSettlement or source.status == Refund.Status.SUCCEEDED) else 0},
                              refund_status=source.status if model is Refund else "",
                              method=source.method or getattr(source, "provider", ""), reference=source.reference,
                              effective=effective, document_number=doc.number if doc else "")
