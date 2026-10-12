"""Scheduled report delivery audit edges (forward plan phase 6, reports lane).

Schedule ids remap to the exported `ReportSchedule` row. Delivery ids name omitted
delivery telemetry (`ReportDelivery` never travels), so they are snapshotted, not bound.
"""

from .audit_references_targets import AuditReference, AuditReferenceDisposition

R = AuditReferenceDisposition.REMAP
S = AuditReferenceDisposition.SOURCE_LOCAL_SNAPSHOT

_SCHEDULE_ACTIONS = (
    "report_schedule.created", "report_schedule.updated", "report_schedule.deleted",
    "report_schedule.skipped", "report_schedule.delivered", "report_schedule.failed",
)

REPORT_SCHEDULE_AUDIT_EDGES = {
    **{
        (action, "schedule_id"): AuditReference(R, "operations.ReportSchedule")
        for action in _SCHEDULE_ACTIONS
    },
    ("report_schedule.delivered", "delivery_id"): AuditReference(S, "operations.ReportDelivery"),
    ("report_schedule.failed", "delivery_id"): AuditReference(S, "operations.ReportDelivery"),
}
