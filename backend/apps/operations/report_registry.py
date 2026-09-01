from dataclasses import dataclass
from typing import Callable

from django.utils.module_loading import import_string
from rest_framework.exceptions import APIException

from apps.accounts import rbac


@dataclass(frozen=True)
class ReportResult:
    field_order: tuple[str, ...]
    records: list[dict[str, object]]


@dataclass(frozen=True)
class ReportDefinition:
    key: str
    builder_path: str
    fields: tuple[str, ...]
    required_modules: tuple[str, ...] = ()
    exportable: bool = True
    summary: bool = False
    required_action: str = rbac.Action.VIEW_AUDIT

    def builder(self) -> Callable:
        return import_string(self.builder_path)


class ReportNotFound(APIException):
    status_code = 404

    def __init__(self):
        self.detail = {"detail": "Unknown report key.", "code": "report_not_found"}


class ReportNotExportable(APIException):
    status_code = 400

    def __init__(self):
        self.detail = {"detail": "Report is not exportable.", "code": "report_not_exportable"}


def _legacy(key, fields, *, exportable=True, summary=False):
    path = f"apps.operations.reports_inventory.build_{key.replace('-', '_')}"
    return ReportDefinition(key, path, fields, exportable=exportable, summary=summary)


REPORT_DEFINITIONS = (
    _legacy("summary", (), exportable=False, summary=True),
    _legacy("taken-items", ("product", "issued_quantity")),
    _legacy("active-loans", ("id", "requester", "status", "issued_at")),
    _legacy("returns", ("id", "requester", "status", "closed_at")),
    _legacy("damaged-missing", ("product", "damaged_quantity", "missing_quantity")),
    _legacy("damaged-lost", ("product_name", "damaged_quantity", "lost_quantity")),
    _legacy("qr-scans", ("context", "count")),
    _legacy("most-lent", ("product_name", "times_lent", "total_quantity_lent")),
    _legacy("top-borrowers", ("holder", "requests", "items_borrowed")),
    _legacy("recently-added", ("product_name", "created_at", "total_quantity")),
    ReportDefinition("machine-usage", "apps.operations.reports_machine_usage.build_machine_usage", ("machine_id", "machine_name", "machine_type", "is_active", "usage_entries", "usage_hours"), ("machines",)),
    ReportDefinition("event-attendance", "apps.operations.reports_events.build_event_attendance", ("event_id", "title", "starts_at", "status", "capacity", "registrations", "confirmed", "registered", "waitlisted", "cancelled", "attended", "attendance_rate_percent", "organizers"), ("events",)),
    ReportDefinition("booking-utilization", "apps.operations.reports_bookings.build_booking_utilization", ("space_id", "space_name", "kind", "is_active", "booked", "completed", "no_show", "cancelled", "upcoming", "reserved_hours", "completed_hours", "window_hours", "reservation_utilization_percent", "no_show_rate_percent"), ("bookings",)),
    ReportDefinition("maintenance-activity", "apps.operations.reports_maintenance.build_maintenance_activity", ("machine_id", "machine_name", "machine_type", "is_active", "log_count", "costed_log_count", "total_cost", "average_cost", "last_performed_at", "average_interval_days", "active_schedules", "overdue_schedules"), ("machines", "maintenance")),
    ReportDefinition("member-activity", "apps.operations.reports_members.build_member_activity", ("makerspace_name", "membership_policy", "referrals_enabled", "new_members", "active_members", "revoked_members", "pending_requests", "open_invites", "referred_joins", "verified_members")),
    ReportDefinition("machine-service", "apps.machines.service_reports.build_machine_service_report", ("row_kind", "submitted", "accepted", "in_progress", "completed", "collected", "rejected", "failed", "machine_id", "machine_name", "machine_type", "request_count", "completed_count", "failed_count", "completed_hours", "failed_partial_hours", "total_recorded_service_hours", "failure_rate", "measurement", "product_id", "product_label", "completed_amount", "failed_partial_amount", "total_used", "outcome", "failed_count_amount", "failed_grams_amount"), ("machine_service",)),
    ReportDefinition("printer-service", "apps.machines.service_reports.build_printer_service_report", ("machine_id", "machine_name", "model", "completed_hours", "failed_partial_hours", "manual_hours", "consumed_grams", "payment_due", "payment_paid"), ("machine_service",)),
    ReportDefinition("fablab-health", "apps.operations.reports_health.build_fablab_health", (
        "events_enabled", "events_available", "events_in_period", "events_registrations", "events_attended", "events_completed_attendance_rate_percent",
        "bookings_enabled", "bookings_available", "bookings_active_spaces", "bookings_non_cancelled", "bookings_reserved_hours", "bookings_upcoming", "bookings_no_shows", "bookings_reservation_utilization_percent",
        "machines_enabled", "machines_available", "machines_active", "machines_usage_hours",
        "maintenance_enabled", "maintenance_available", "maintenance_logs", "maintenance_total_cost", "maintenance_overdue_schedules",
    )),
    ReportDefinition(
        "payment-reconciliation",
        "apps.operations.reports_payments.build_payment_reconciliation",
        ("currency", "subject_type", "status", "payment_count", "amount_total", "outstanding_amount"),
        required_action=rbac.Action.MANAGE_MAKERSPACE,
    ),
)

REPORT_REGISTRY = {definition.key: definition for definition in REPORT_DEFINITIONS}
REPORT_KEYS = [definition.key for definition in REPORT_DEFINITIONS]


def report_definition(report_key, *, for_export=False):
    definition = REPORT_REGISTRY.get(report_key)
    if definition is None:
        raise ReportNotFound()
    if for_export and not definition.exportable:
        raise ReportNotExportable()
    return definition
