"""Curated numeric metrics: dates, labels and IDs cannot become thresholds."""

NUMERIC_FIELDS = frozenset({
    "count", "issued_quantity", "damaged_quantity", "missing_quantity", "lost_quantity",
    "times_lent", "total_quantity_lent", "requests", "items_borrowed", "total_quantity",
    "usage_entries", "usage_hours", "registrations", "confirmed", "pending_approval",
    "registered", "waitlisted", "rejected", "cancelled", "attended", "attendance_rate_percent",
    "booked", "completed", "no_show", "upcoming", "reserved_hours", "completed_hours",
    "log_count", "total_cost", "active_schedules", "overdue_schedules", "new_members",
    "active_members", "revoked_members", "pending_requests", "open_invites", "verified_members",
    "payment_count", "amount_total", "outstanding_amount", "refunded_amount", "collected_amount",
    "net_amount", "request_count", "quantity", "jobs", "total_rows", "error_rows", "warning_rows",
    "created_count", "attached_count", "unattached_count", "object_expired_count", "bytes",
    "delivery_count", "attempt_count", "success_rate_percent", "activity_count", "failure_count",
    "cohort_members", "eligible_members", "retained_members", "retention_percent", "churned_members",
    "reactivated_members", "recurring_members", "mrr", "arr", "arpu",
})


def condition_metrics(definition):
    return tuple(field for field in definition.fields if field in NUMERIC_FIELDS)
