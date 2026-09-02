from apps.accounts import rbac
from apps.operations.report_types import ReportDefinition


COVERAGE_REPORT_DEFINITIONS = (
    ReportDefinition(
        "loan-throughput", "apps.operations.reports_workflow.build_loan_throughput",
        ("period", "source", "request_status", "request_count", "unique_borrowers", "anonymous_requests", "requested_units", "accepted_units", "issued_units", "returned_units", "damaged_units", "missing_units", "average_approval_hours", "average_loan_hours"),
        title="Loan throughput", chart_hint="stacked_line", grains=("day", "month"), section_modules=("guest_handover",),
    ),
    ReportDefinition(
        "inventory-control", "apps.operations.reports_inventory_control.build_inventory_control",
        ("module_key", "metric_key", "dimension", "count", "quantity", "rate_percent", "last_activity_at"),
        title="Inventory control", chart_hint="grouped_bar",
        section_modules=("public_inventory", "qr_management", "containers", "stock_transfers", "stocktake", "qr_print_batches", "asset_units"),
    ),
    ReportDefinition(
        "evidence-compliance", "apps.evidence.reports.build_evidence_compliance",
        ("period", "evidence_type", "created_count", "attached_count", "unattached_count", "object_live_count", "object_expired_count", "metadata_retained_count", "bytes", "attachment_rate_percent"),
        ("evidence_uploads",), title="Evidence compliance", chart_hint="line", grains=("day", "month"),
    ),
    ReportDefinition(
        "import-quality", "apps.admin_api.reports_imports.build_import_quality",
        ("period", "mode", "status", "jobs", "total_rows", "processed_rows", "created_rows", "updated_rows", "error_rows", "warning_rows", "success_rate_percent", "last_activity_at"),
        ("bulk_import",), required_action=rbac.Action.EDIT_INVENTORY,
        title="Import quality", chart_hint="stacked_bar", grains=("day", "month"),
    ),
    ReportDefinition(
        "procurement-performance", "apps.procurement.reports.build_procurement_performance",
        ("period", "kind", "status", "items", "units", "estimated_total", "actual_total", "received_items", "inventoried_items", "average_order_hours", "average_receive_hours", "last_activity_at"),
        ("procurement",), required_action=rbac.Action.EDIT_INVENTORY,
        title="Procurement performance", chart_hint="stacked_bar", grains=("day", "month"),
    ),
    ReportDefinition(
        "communications-health", "apps.integrations.reports_communications.build_communications_health",
        ("module_key", "channel", "feature", "status", "delivery_count", "attempt_count", "destination_count", "success_rate_percent", "unread_count", "last_activity_at"),
        required_action=rbac.Action.MANAGE_MAKERSPACE, title="Communications health",
        chart_hint="stacked_bar", section_modules=("notifications", "email", "telegram", "slack", "mattermost", "discord"),
    ),
    ReportDefinition(
        "community-engagement", "apps.makerspaces.reports_community.build_community_engagement",
        ("period", "module_key", "enabled", "activations", "revocations", "active_accounts", "approved_apps", "active_grants", "revoked_grants", "reuse_detected"),
        title="Community engagement", chart_hint="line", grains=("day", "month"),
        section_modules=("membership", "member_accounts", "mobile"),
    ),
    ReportDefinition(
        "module-operational-health", "apps.operations.reports_module_health.build_module_operational_health",
        ("module_key", "enabled", "runtime_available", "coverage_kind", "activity_count", "failure_count", "last_activity_at", "rollup_watermark", "rollup_state"),
        required_action=rbac.Action.MANAGE_MAKERSPACE, title="Module operational health",
        chart_hint="status_grid", section_modules=(
            "public_inventory", "request_workflow", "staff_admin", "guest_handover", "scanner", "printing", "telegram", "evidence_uploads", "qr_management", "bulk_import", "containers", "stock_transfers", "stocktake", "reports", "qr_print_batches", "asset_units", "procurement", "machines", "machine_service", "events", "bookings", "maintenance", "membership", "notifications", "email", "slack", "mattermost", "discord", "payments", "member_accounts", "mobile", "updates",
        ),
    ),
)
