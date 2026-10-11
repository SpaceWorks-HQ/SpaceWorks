"""Recurring-plan projection at each local month end, independent of payment rails."""

from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from dateutil.relativedelta import relativedelta
from django.utils import timezone

from apps.accounts import rbac
from apps.audit.models import AuditLog
from apps.makerspaces.local_time import local_day_bounds, to_local
from apps.makerspaces.models import Makerspace, MembershipTerm
from apps.operations.membership_report_history import membership_intervals
from apps.operations.membership_report_scope import report_queryset
from apps.operations.report_scope import scoped_ids
from apps.operations.report_types import ReportResult
from apps.payments.models import Payment

FIELDS = ("period", "currency", "recurring_members", "mrr", "arr", "arpu", "churned_members", "reactivated_members")


def build_membership_revenue(makerspace_id, *, limit=None, date_range=None, grain="month", now=None, actor=None):
    now = now or timezone.now()
    records = []
    spaces = Makerspace.objects.filter(
        pk__in=scoped_ids(makerspace_id, "membership"),
    )
    spaces = (rbac.scope_by_action(actor, rbac.Action.VIEW_FINANCE, spaces, field="id") if actor
              else rbac.scope_for_scheduled_work(spaces, field="id")).order_by("pk")
    for space in spaces:
        records.extend(_space_rows(space, date_range, now, makerspace_id is None, actor))
    fields = (("makerspace_id",) + FIELDS) if makerspace_id is None else FIELDS
    return ReportResult(fields, records if limit is None else records[:limit], {
        "grain": "month", "definition": "Month-end recurring-plan projection: monthly price or yearly price / 12, per currency; ARR = MRR * 12; ARPU = MRR / recurring members.",
        "limitations": "Uses current plan prices and current waiver state; no historical price snapshots exist. Custom-day plans and waived term charges are excluded. Churn/reactivation count recurring coverage gaps.",
    })


def _space_rows(space, date_range, now, aggregate, actor):
    action = rbac.Action.VIEW_FINANCE
    terms = list(report_queryset(
        MembershipTerm.objects.filter(plan__makerspace=space, plan__interval__in=["monthly", "yearly"]),
        space.pk, action, actor=actor, field="membership__makerspace_id",
    ).values("id", "membership_id", "starts_at", "ends_at", "status", "plan__interval", "plan__amount", "plan__currency"))
    waived = set(report_queryset(Payment.objects.filter(
        subject_type=Payment.SubjectType.MEMBERSHIP_TERM, status=Payment.Status.WAIVED,
    ), space.pk, action, actor=actor).values_list("subject_id", flat=True))
    cancellations = dict(report_queryset(AuditLog.objects.filter(
        target_type="makerspaces.membershipterm", action="membership.term_cancelled",
    ), space.pk, action, actor=actor).order_by("created_at").values_list("target_id", "created_at"))
    memberships = membership_intervals(space, actor=actor, action=action)
    coverage = defaultdict(list)
    for term in terms:
        if term["id"] in waived:
            continue
        end = term["ends_at"]
        if term["status"] == "cancelled":
            cancelled = cancellations.get(str(term["id"]))
            if cancelled is None:
                continue  # No timestamp: historical coverage cannot be established.
            end = min(end, cancelled)
        price = term["plan__amount"] / (12 if term["plan__interval"] == "yearly" else 1)
        for start, stopped in memberships.get(term["membership_id"], []):
            left, right = max(start, term["starts_at"]), min(stopped or end, end)
            if left < right:
                coverage[(term["plan__currency"], term["membership_id"])].append((left, right, price, term["id"]))
    if not coverage:
        return []
    first = date_range[0] if date_range and date_range[0] else min(t[0] for spans in coverage.values() for t in spans)
    last = min(now, date_range[1]) if date_range and date_range[1] else now
    month = to_local(space, first).date().replace(day=1)
    rows = []
    while True:
        following = month + relativedelta(months=1)
        left = local_day_bounds(space, month)[0]
        if left >= last:
            break
        left = max(left, first)
        right = min(local_day_bounds(space, following)[0], last)
        snapshot = right - timedelta(microseconds=1)
        by_currency = defaultdict(lambda: {"prices": [], "churn": 0, "reactivation": 0})
        for (currency, _member), spans in coverage.items():
            values = by_currency[currency]
            live = [span for span in spans if span[0] <= snapshot < span[1]]
            if live:
                # Overlapping terms count a member once: the latest starting term wins.
                values["prices"].append(max(live, key=lambda t: (t[0], t[3]))[2])
            merged = []
            for start, end, *_ in sorted(spans):
                if merged and start <= merged[-1][1]:
                    merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
                else:
                    merged.append((start, end))
            values["churn"] += any(left <= end < right for _, end in merged)
            values["reactivation"] += any(left <= start < right for start, _ in merged[1:])
        for currency, values in sorted(by_currency.items()):
            count = len(values["prices"])
            mrr = sum(values["prices"], Decimal(0))
            cent = Decimal("0.01")
            row = {"period": month.isoformat(), "currency": currency, "recurring_members": count,
                   "mrr": mrr.quantize(cent), "arr": (mrr * 12).quantize(cent),
                   "arpu": (mrr / count if count else Decimal(0)).quantize(cent),
                   "churned_members": values["churn"], "reactivated_members": values["reactivation"]}
            if aggregate:
                row["makerspace_id"] = space.pk
            rows.append(row)
        month = following
    return rows
