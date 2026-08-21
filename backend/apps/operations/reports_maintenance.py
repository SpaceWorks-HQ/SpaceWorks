from decimal import Decimal, ROUND_HALF_UP

from django.db.models import Avg, Count, DateTimeField, DecimalField, IntegerField, Max, Min, OuterRef, Q, Subquery, Sum, Value
from django.db.models.functions import Coalesce
from django.utils import timezone

from apps.machines.models import Machine
from apps.operations.report_registry import ReportResult
from apps.operations.report_scope import scoped_ids


FIELDS = (
    "machine_id", "machine_name", "machine_type", "is_active", "log_count",
    "costed_log_count", "total_cost", "average_cost", "last_performed_at",
    "average_interval_days", "active_schedules", "overdue_schedules",
)
CENT = Decimal("0.01")


def build_maintenance_activity(makerspace_id, *, limit=None, date_range=None):
    from apps.maintenance.models import MaintenanceLog, MaintenanceSchedule

    aggregate = makerspace_id is None
    today = timezone.localdate()
    log_filter = Q()
    if date_range:
        start, end = date_range
        if start is not None:
            log_filter &= Q(performed_at__gte=start)
        if end is not None:
            log_filter &= Q(performed_at__lt=end)
    logs = MaintenanceLog.objects.filter(machine_id=OuterRef("pk")).filter(log_filter).values("machine_id")
    log_stats = logs.annotate(
        count=Count("id"), costed=Count("id", filter=Q(cost__isnull=False)),
        total=Coalesce(Sum("cost"), Value(Decimal("0.00"))),
        average=Avg("cost"), first=Min("performed_at"), last=Max("performed_at"),
    )
    schedules = MaintenanceSchedule.objects.filter(machine_id=OuterRef("pk"), is_active=True).values("machine_id").annotate(
        active=Count("id"), overdue=Count("id", filter=Q(next_due__lt=today)),
    )
    qs = Machine.objects.filter(
        makerspace_id__in=scoped_ids(makerspace_id, "machines", "maintenance")
    ).values("id", "makerspace_id", "name", "machine_type__name", "is_active").annotate(
        logs=Coalesce(Subquery(log_stats.values("count")[:1], output_field=IntegerField()), Value(0)),
        costed=Coalesce(Subquery(log_stats.values("costed")[:1], output_field=IntegerField()), Value(0)),
        total=Coalesce(Subquery(log_stats.values("total")[:1], output_field=DecimalField(max_digits=20, decimal_places=2)), Value(Decimal("0.00"))),
        average=Subquery(log_stats.values("average")[:1], output_field=DecimalField(max_digits=20, decimal_places=2)),
        first=Subquery(log_stats.values("first")[:1], output_field=DateTimeField()),
        last=Subquery(log_stats.values("last")[:1], output_field=DateTimeField()),
        active=Coalesce(Subquery(schedules.values("active")[:1], output_field=IntegerField()), Value(0)),
        overdue=Coalesce(Subquery(schedules.values("overdue")[:1], output_field=IntegerField()), Value(0)),
    )
    records = [_record(row, aggregate) for row in list(qs)]
    records.sort(key=lambda row: _sort_key(row, aggregate))
    if limit is not None:
        records = records[:limit]
    fields = (("makerspace_id",) + FIELDS) if aggregate else FIELDS
    return ReportResult(fields, records)


def _record(row, aggregate):
    interval = None
    interval_total_days = None
    interval_gap_count = max(row["logs"] - 1, 0)
    if row["logs"] >= 2:
        elapsed = row["last"] - row["first"]
        interval_total_days = (
            Decimal(elapsed.days)
            + Decimal(elapsed.seconds) / Decimal(86400)
            + Decimal(elapsed.microseconds) / Decimal(86_400_000_000)
        )
        interval = round(float(interval_total_days / interval_gap_count), 2)
    record = {
        "machine_id": row["id"], "machine_name": row["name"],
        "machine_type": row["machine_type__name"], "is_active": row["is_active"],
        "log_count": row["logs"], "costed_log_count": row["costed"],
        "total_cost": (row["total"] or Decimal("0.00")).quantize(CENT),
        "average_cost": row["average"].quantize(CENT, rounding=ROUND_HALF_UP) if row["average"] is not None else None,
        "last_performed_at": row["last"], "average_interval_days": interval,
        "active_schedules": row["active"], "overdue_schedules": row["overdue"],
        # Internal aggregation inputs deliberately stay outside FIELDS. Existing
        # single-space API and export schemas therefore remain byte-for-byte stable.
        "_interval_total_days": interval_total_days,
        "_interval_gap_count": interval_gap_count,
    }
    if aggregate:
        record["makerspace_id"] = row["makerspace_id"]
    return record


def _sort_key(row, aggregate):
    prefix = (row["makerspace_id"],) if aggregate else ()
    return (*prefix, -row["overdue_schedules"], -row["log_count"], row["machine_name"], row["machine_id"])
