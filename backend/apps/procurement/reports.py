from django.db.models import Avg, Count, DurationField, ExpressionWrapper, F, Max, Q, Sum

from apps.operations.report_scope import scoped_ids
from apps.operations.report_types import ReportResult
from apps.operations.reports_common import apply_range, limited, period_expression
from apps.procurement.models import ToBuyItem


FIELDS = (
    "period", "kind", "status", "items", "units", "estimated_total", "actual_total",
    "received_items", "inventoried_items", "average_order_hours", "average_receive_hours",
    "last_activity_at",
)


def build_procurement_performance(makerspace_id, *, limit=None, date_range=None, grain="day"):
    aggregate = makerspace_id is None
    group = ["period", "kind", "status"]
    if aggregate:
        group.insert(0, "makerspace_id")
    qs = apply_range(ToBuyItem.objects.filter(
        makerspace_id__in=scoped_ids(makerspace_id, "procurement")
    ), "created_at", date_range).annotate(
        period=period_expression("created_at", grain),
        estimated_line=F("estimated_unit_cost") * F("quantity"),
        actual_line=F("actual_unit_cost") * F("quantity"),
        order_duration=ExpressionWrapper(F("ordered_at") - F("created_at"), output_field=DurationField()),
        receive_duration=ExpressionWrapper(F("received_at") - F("ordered_at"), output_field=DurationField()),
    ).values(*group).annotate(
        items=Count("id"), units=Sum("quantity"), estimated_total=Sum("estimated_line"),
        actual_total=Sum("actual_line"), received_items=Count("id", filter=Q(received_at__isnull=False)),
        inventoried_items=Count("id", filter=Q(moved_to_inventory_at__isnull=False)),
        average_order=Avg("order_duration"), average_receive=Avg("receive_duration"),
        last_activity_at=Max("updated_at"),
    ).order_by(*group)
    records = []
    for row in qs:
        row["average_order_hours"] = _hours(row.pop("average_order"))
        row["average_receive_hours"] = _hours(row.pop("average_receive"))
        records.append(row)
    fields = (("makerspace_id",) + FIELDS) if aggregate else FIELDS
    return ReportResult(fields, limited(records, limit))


def _hours(value):
    return round(value.total_seconds() / 3600, 2) if value else None
