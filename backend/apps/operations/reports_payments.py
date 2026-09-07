from django.db.models import (
    Case,
    CharField,
    Count,
    DecimalField,
    OuterRef,
    Q,
    Subquery,
    Sum,
    Value,
    When,
)
from django.db.models.functions import Coalesce

from apps.operations.report_registry import ReportResult
from apps.operations.report_scope import scoped_ids
from apps.payments.models import ManualSettlement, Payment

FIELDS = (
    "currency",
    "subject_type",
    "status",
    # How settled money actually arrived: the manual method (cash / UPI / bank transfer /
    # card machine / cheque) for an offline settlement, the vendor for an online one, and
    # "" for rows where nothing has been collected. Splitting on it is what makes the
    # report reconcile against a physical cash box.
    "settlement_method",
    "payment_count",
    "amount_total",
    "outstanding_amount",
)


def build_payment_reconciliation(
    makerspace_id,
    *,
    limit=None,
    date_range=None,
    subject_type=None,
    status=None,
):
    aggregate = makerspace_id is None
    queryset = Payment.objects.filter(makerspace_id__in=scoped_ids(makerspace_id))
    if subject_type:
        queryset = queryset.filter(subject_type=subject_type)
    if status:
        queryset = queryset.filter(status=status)
    if date_range:
        start, end = date_range
        dated = Q()
        if start is not None:
            dated &= Q(created_at__gte=start)
        if end is not None:
            dated &= Q(created_at__lt=end)
        queryset = queryset.filter(Q(status=Payment.Status.PENDING) | dated)

    # A settled row's method comes from the effective (unamended) receipt; an online
    # charge reports its vendor instead, so one column answers "where did this money come
    # from" for both rails. Currencies are never combined -- `currency` stays a grouping
    # key, so a space taking both INR and USD gets one row per currency, never a total
    # that silently adds them.
    queryset = queryset.annotate(
        settlement_method=Case(
            When(
                status=Payment.Status.PAID_OFFLINE,
                then=Coalesce(
                    Subquery(
                        ManualSettlement.objects.filter(
                            payment_id=OuterRef("pk"), amended_by__isnull=True
                        )
                        .order_by("-created_at", "-pk")
                        .values("method")[:1]
                    ),
                    # Settled before the ledger existed, or by a path that recorded no
                    # receipt. Reported honestly rather than folded into "cash".
                    Value("unknown"),
                ),
            ),
            When(status=Payment.Status.PAID_ONLINE, then="provider"),
            default=Value(""),
            output_field=CharField(),
        )
    )
    group_fields = [
        "makerspace_id", "currency", "subject_type", "status", "settlement_method"
    ]
    fields = (("makerspace_id",) + FIELDS) if aggregate else FIELDS
    money = DecimalField(max_digits=20, decimal_places=2)
    rows = (
        queryset.values(*group_fields)
        .annotate(
            payment_count=Count("pk"),
            amount_total=Sum("amount"),
            outstanding_amount=Sum(
                Case(
                    When(status=Payment.Status.PENDING, then="amount"),
                    default=Value(0),
                    output_field=money,
                )
            ),
        )
        .values(*fields)
        .order_by(*group_fields)
    )
    if limit is not None:
        rows = rows[:limit]
    return ReportResult(fields, list(rows))
