from django.db.models import Count, Max, Sum

from apps.admin_api.models import BulkImportJob
from apps.operations.report_types import ReportResult
from apps.operations.reports_common import apply_range, limited, period_expression
from apps.operations.report_scope import scoped_ids


FIELDS = (
    "period", "mode", "status", "jobs", "total_rows", "processed_rows",
    "created_rows", "updated_rows", "error_rows", "warning_rows",
    "success_rate_percent", "last_activity_at",
)


def build_import_quality(makerspace_id, *, limit=None, date_range=None, grain="day"):
    aggregate = makerspace_id is None
    group = ["period", "mode", "status"]
    if aggregate:
        group.insert(0, "makerspace_id")
    rows = apply_range(BulkImportJob.objects.filter(
        makerspace_id__in=scoped_ids(makerspace_id, "bulk_import")
    ), "created_at", date_range).annotate(
        period=period_expression("created_at", grain)
    ).values(*group).annotate(
        jobs=Count("id"), total_rows=Sum("total_rows"), processed_rows=Sum("processed_rows"),
        created_rows=Sum("created_count"), updated_rows=Sum("updated_count"),
        error_rows=Sum("error_count"), warning_rows=Sum("warning_count"),
        last_activity_at=Max("updated_at"),
    ).order_by(*group)
    records = []
    for row in rows:
        successful = (row["created_rows"] or 0) + (row["updated_rows"] or 0)
        processed = row["processed_rows"] or 0
        records.append({**row, "success_rate_percent": round(successful / processed * 100, 2) if processed else None})
    fields = (("makerspace_id",) + FIELDS) if aggregate else FIELDS
    return ReportResult(fields, limited(records, limit))
