from apps.accounts import rbac
from apps.operations.report_types import ReportDefinition


def _legacy(key, fields, *, exportable=True, summary=False, chart_hint="bar"):
    path = f"apps.operations.reports_inventory.build_{key.replace('-', '_')}"
    return ReportDefinition(
        key, path, fields, exportable=exportable, summary=summary,
        title=key.replace("-", " ").title(), chart_hint=chart_hint,
    )


EXISTING_REPORT_DEFINITIONS = (
    _legacy("summary", (), exportable=False, summary=True, chart_hint="stats"),
    _legacy("taken-items", ("product", "issued_quantity")),
    _legacy("active-loans", ("id", "requester", "status", "issued_at"), chart_hint="line"),
    _legacy("returns", ("id", "requester", "status", "closed_at"), chart_hint="line"),
    _legacy("damaged-missing", ("product", "damaged_quantity", "missing_quantity"), chart_hint="grouped_bar"),
    _legacy("damaged-lost", ("product_name", "damaged_quantity", "lost_quantity"), chart_hint="grouped_bar"),
    _legacy("qr-scans", ("context", "count"), chart_hint="donut"),
    _legacy("most-lent", ("product_name", "times_lent", "total_quantity_lent")),
    _legacy("top-borrowers", ("holder", "requests", "items_borrowed"), chart_hint="grouped_bar"),
    _legacy("recently-added", ("product_name", "created_at", "total_quantity"), chart_hint="line"),
    ReportDefinition("machine-usage", "apps.operations.reports_machine_usage.build_machine_usage", ("machine_id", "machine_name", "machine_type", "is_active", "usage_entries", "usage_hours"), ("machines",), title="Machine usage", chart_hint="bar"),
    ReportDefinition("event-attendance", "apps.operations.reports_events.build_event_attendance", ("event_id", "series_id", "series_title", "series_occurrence_key", "title", "starts_at", "status", "capacity", "registrations", "confirmed", "pending_approval", "registered", "waitlisted", "rejected", "cancelled", "attended", "attendance_rate_percent", "feedback_responses", "active_certificates", "revoked_certificates", "organizers"), ("events",), title="Event attendance", chart_hint="line"),
    ReportDefinition("booking-utilization", "apps.operations.reports_bookings.build_booking_utilization", ("space_id", "space_name", "kind", "is_active", "booked", "completed", "no_show", "cancelled", "upcoming", "reserved_hours", "completed_hours", "window_hours", "reservation_utilization_percent", "no_show_rate_percent"), ("bookings",), title="Booking utilization", chart_hint="line"),
    ReportDefinition("maintenance-activity", "apps.operations.reports_maintenance.build_maintenance_activity", ("machine_id", "machine_name", "machine_type", "is_active", "log_count", "costed_log_count", "total_cost", "average_cost", "last_performed_at", "average_interval_days", "active_schedules", "overdue_schedules"), ("machines", "maintenance"), title="Maintenance activity", chart_hint="line"),
    ReportDefinition("member-activity", "apps.operations.reports_members.build_member_activity", ("makerspace_name", "membership_policy", "referrals_enabled", "new_members", "active_members", "revoked_members", "pending_requests", "open_invites", "referred_joins", "verified_members"), ("membership",), title="Member activity", chart_hint="bar"),
    ReportDefinition("machine-service", "apps.machines.service_reports.build_machine_service_report", ("row_kind", "submitted", "accepted", "in_progress", "completed", "collected", "rejected", "failed", "machine_id", "machine_name", "machine_type", "request_count", "completed_count", "failed_count", "completed_hours", "failed_partial_hours", "total_recorded_service_hours", "failure_rate", "measurement", "product_id", "product_label", "completed_amount", "failed_partial_amount", "total_used", "outcome", "failed_count_amount", "failed_grams_amount"), ("machine_service",), title="Machine service", chart_hint="grouped_bar"),
    ReportDefinition("printer-service", "apps.machines.service_reports.build_printer_service_report", ("machine_id", "machine_name", "model", "completed_hours", "failed_partial_hours", "manual_hours", "consumed_grams", "payment_due", "payment_paid"), ("printing",), title="Printer service", chart_hint="grouped_bar"),
    ReportDefinition("fablab-health", "apps.operations.reports_health.build_fablab_health", (
        "events_enabled", "events_available", "events_in_period", "events_registrations", "events_attended", "events_completed_attendance_rate_percent",
        "bookings_enabled", "bookings_available", "bookings_active_spaces", "bookings_non_cancelled", "bookings_reserved_hours", "bookings_upcoming", "bookings_no_shows", "bookings_reservation_utilization_percent",
        "machines_enabled", "machines_available", "machines_active", "machines_usage_hours",
        "maintenance_enabled", "maintenance_available", "maintenance_logs", "maintenance_total_cost", "maintenance_overdue_schedules",
    ), title="FabLab health", chart_hint="status_grid", section_modules=("events", "bookings", "machines", "maintenance")),
    ReportDefinition(
        "payment-reconciliation", "apps.operations.reports_payments.build_payment_reconciliation",
        ("currency", "subject_type", "status", "payment_count", "amount_total", "outstanding_amount"),
        required_action=rbac.Action.MANAGE_MAKERSPACE, title="Payment reconciliation",
        chart_hint="stacked_bar",
    ),
)
