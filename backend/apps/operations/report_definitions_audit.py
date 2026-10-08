"""The ``audit-trail`` report: tenant-only, CSV-only, export-only, never scheduled."""

from apps.accounts import rbac
from apps.operations.report_types import ReportDefinition

AUDIT_REPORT_DEFINITIONS = (
    ReportDefinition(
        "audit-trail",
        "apps.operations.reports_audit.build_audit_trail",
        ("created_at", "actor", "action", "action_label", "target_type", "target_id", "meta"),
        # The reports route already requires the `reports` module; staff_admin is core.
        required_modules=(),
        required_action=rbac.Action.VIEW_AUDIT,
        exportable=True,
        title="Audit trail",
        chart_hint="table",
        version=1,
        allowed_formats=("csv",),
        # Email/chat delivery would broaden custody of accountability data.
        schedulable=False,
        # A JSON preview would be a second audit list beside /admin/audit-logs.
        previewable=False,
        # Rows must keep their tenant; no deployment-wide surface may flatten them.
        deployment_aggregate=False,
    ),
)
