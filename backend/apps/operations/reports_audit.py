"""Builder for the ``audit-trail`` CSV: the same projection as the staff audit list.

Every row passes through ``apps.audit.presentation.project``, so the file can never show
a metadata path the API hides. The builder refuses ``makerspace_id=None`` as defense in
depth: even an internal caller that bypassed the aggregate-surface capability check
cannot flatten audit rows without their tenant.
"""

import json

from apps.audit.models import AuditLog
from apps.audit.presentation import project
from apps.operations.report_types import ReportResult

MAX_AUDIT_EXPORT_ROWS = 10_000
FIELDS = ("created_at", "actor", "action", "action_label", "target_type", "target_id", "meta")


def build_audit_trail(
    makerspace_id, *, limit=None, date_range=None, action=None, target_type=None,
    target_id=None, actor=None,
):
    if not makerspace_id:
        raise ValueError("The audit-trail report is tenant-only.")
    rows = AuditLog.objects.filter(makerspace_id=makerspace_id).select_related("actor")
    if date_range:
        start, end = date_range
        if start:
            rows = rows.filter(created_at__gte=start)
        if end:
            rows = rows.filter(created_at__lt=end)
    for lookup, value in (
        ("action", action), ("target_type", target_type), ("target_id", target_id),
        ("actor_id", actor),
    ):
        if value not in (None, ""):
            rows = rows.filter(**{lookup: value})
    records = []
    for row in rows.order_by("-created_at", "-pk")[:MAX_AUDIT_EXPORT_ROWS]:
        projection = project(row)
        actor_obj = row.actor
        records.append({
            "created_at": row.created_at,
            "actor": (actor_obj.get_full_name() or actor_obj.get_username()) if actor_obj else "",
            "action": row.action,
            "action_label": projection.action_label,
            "target_type": row.target_type,
            "target_id": row.target_id,
            "meta": json.dumps(projection.meta, sort_keys=True, separators=(",", ":")),
        })
    return ReportResult(FIELDS, records, {"row_cap": MAX_AUDIT_EXPORT_ROWS})
