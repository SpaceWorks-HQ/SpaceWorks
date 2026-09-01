from collections import defaultdict

from django.db.models import Count, Max

from apps.audit.models import AuditLog
from apps.boxes.models import QrScanEvent
from apps.makerspaces.module_registry import MODULES, module_available
from apps.makerspaces.platform import module_enabled
from apps.operations.report_coverage import REPORT_MODULE_COVERAGE
from apps.operations.report_types import ReportResult
from apps.operations.reports_common import limited, report_spaces


FIELDS = (
    "module_key", "enabled", "runtime_available", "coverage_kind",
    "activity_count", "failure_count", "last_activity_at", "rollup_watermark",
    "rollup_state",
)

ACTION_MODULES = {
    "hardware": "request_workflow", "request": "request_workflow",
    "admin_direct": "guest_handover", "evidence": "evidence_uploads",
    "qr": "qr_management", "bulk_import": "bulk_import", "container": "containers",
    "stock_transfer": "stock_transfers", "stocktake": "stocktake",
    "procurement": "procurement", "machine": "machines", "service": "machine_service",
    "event": "events", "booking": "bookings", "maintenance": "maintenance",
    "membership": "membership", "notification": "notifications", "email": "email",
    "payment": "payments", "device": "mobile", "report": "reports",
}


def build_module_operational_health(makerspace_id, *, limit=None, date_range=None):
    aggregate = makerspace_id is None
    records = []
    for space in report_spaces(makerspace_id):
        activity = _audit_activity(space.id, date_range)
        if module_enabled(space, "scanner"):
            scanner = QrScanEvent.objects.filter(makerspace=space).aggregate(
                count=Count("id"), last=Max("created_at")
            )
            activity["scanner"]["count"] += scanner["count"]
            activity["scanner"]["last"] = scanner["last"] or activity["scanner"]["last"]
        cursors = _rollup_cursors(space.id)
        for definition in MODULES:
            enabled = module_enabled(space, definition.key)
            state = activity[definition.key] if enabled else {"count": 0, "failures": 0, "last": None}
            cursor = cursors.get(definition.key) if enabled else None
            row = {
                "module_key": definition.key,
                "enabled": enabled,
                "runtime_available": module_available(definition.key),
                "coverage_kind": REPORT_MODULE_COVERAGE[definition.key].kind,
                "activity_count": state["count"], "failure_count": state["failures"],
                "last_activity_at": state["last"],
                "rollup_watermark": cursor.rolled_through if cursor else None,
                "rollup_state": "failed" if cursor and cursor.last_error_code else "current" if cursor else "not_started",
            }
            if aggregate:
                row["makerspace_id"] = space.id
            records.append(row)
    fields = (("makerspace_id",) + FIELDS) if aggregate else FIELDS
    return ReportResult(fields, limited(records, limit))


def _audit_activity(space_id, date_range):
    states = defaultdict(lambda: {"count": 0, "failures": 0, "last": None})
    qs = AuditLog.objects.filter(makerspace_id=space_id)
    if date_range:
        start, end = date_range
        if start:
            qs = qs.filter(created_at__gte=start)
        if end:
            qs = qs.filter(created_at__lt=end)
    for row in qs.values("action").annotate(count=Count("id"), last=Max("created_at")):
        prefix = row["action"].split(".", 1)[0]
        module = ACTION_MODULES.get(prefix)
        if not module:
            continue
        states[module]["count"] += row["count"]
        states[module]["last"] = max(filter(None, (states[module]["last"], row["last"])), default=None)
        if any(token in row["action"] for token in ("failed", "rejected", "denied")):
            states[module]["failures"] += row["count"]
    return states


def _rollup_cursors(space_id):
    from apps.operations.models import ReportRollupCursor
    return {row.source_module: row for row in ReportRollupCursor.objects.filter(makerspace_id=space_id)}
