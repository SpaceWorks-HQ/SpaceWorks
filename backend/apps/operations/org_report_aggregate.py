"""Pure row aggregation for organization reports, except identity-aware strategies."""

from decimal import Decimal, ROUND_HALF_UP

from apps.operations.org_report_strategies import LimitSemantics, organization_strategy


CENT = Decimal("0.01")


def aggregate_rows(report_key, rows_by_space, *, limit):
    strategy = organization_strategy(report_key)
    source = rows_by_space
    if strategy.limit_semantics is LimitSemantics.PER_SPACE_THEN_GLOBAL:
        source = [(space_id, rows[:limit]) for space_id, rows in rows_by_space]
    rows = [row for _space_id, space_rows in source for row in space_rows]
    if report_key == "summary":
        return [_summed(rows, strategy.total_fields)] if rows else []
    if report_key == "qr-scans":
        return _group_sum(rows, ("context",), ("count",), limit)
    if report_key == "payment-reconciliation":
        return _group_sum(
            rows, ("currency", "subject_type", "status"),
            ("payment_count", "amount_total", "outstanding_amount"), limit,
        )
    if report_key == "event-attendance":
        return _event_total(rows)
    if report_key == "booking-utilization":
        return _booking_total(rows)
    if report_key == "maintenance-activity":
        return _maintenance_total(rows)
    if report_key == "fablab-health":
        return _health_total(rows)
    if report_key == "evidence-compliance":
        return _evidence_totals(rows, limit)
    return _ordered_rows(report_key, rows)[:limit]


def _summed(rows, fields):
    return {field: _sum(rows, field) for field in fields}


def _sum(rows, field):
    values = [row.get(field) for row in rows if row.get(field) is not None]
    return sum(values, Decimal("0")) if any(isinstance(value, Decimal) for value in values) else sum(values, 0)


def _group_sum(rows, keys, numeric_fields, limit):
    groups = {}
    for row in rows:
        key = tuple(row.get(field) for field in keys)
        target = groups.setdefault(key, {field: row.get(field) for field in keys})
        for field in numeric_fields:
            target[field] = target.get(field, 0) + (row.get(field) or 0)
    return sorted(groups.values(), key=lambda row: tuple(row.get(key) or "" for key in keys))[:limit]


def _event_total(rows):
    if not rows:
        return []
    fields = (
        "capacity", "registrations", "confirmed", "registered", "waitlisted",
        "cancelled", "attended",
    )
    total = _summed(rows, fields)
    completed = [row for row in rows if row.get("status") == "completed"]
    denominator = _sum(completed, "confirmed")
    total["attendance_rate_percent"] = _percent(_sum(completed, "attended"), denominator)
    return [total]


def _booking_total(rows):
    if not rows:
        return []
    fields = (
        "booked", "completed", "no_show", "cancelled", "upcoming",
        "reserved_hours", "completed_hours", "window_hours",
    )
    total = _summed(rows, fields)
    windows = [row.get("window_hours") for row in rows]
    total["window_hours"] = None if not any(value is not None for value in windows) else _sum(rows, "window_hours")
    total["reservation_utilization_percent"] = _percent(
        total["reserved_hours"], total["window_hours"]
    )
    terminal = total["completed"] + total["no_show"]
    total["no_show_rate_percent"] = _percent(total["no_show"], terminal)
    return [total]


def _maintenance_total(rows):
    if not rows:
        return []
    fields = (
        "log_count", "costed_log_count", "total_cost", "active_schedules",
        "overdue_schedules",
    )
    total = _summed(rows, fields)
    total["average_cost"] = _decimal_average(total["total_cost"], total["costed_log_count"])
    timestamps = [row.get("last_performed_at") for row in rows if row.get("last_performed_at")]
    total["last_performed_at"] = max(timestamps) if timestamps else None
    gaps = _sum(rows, "_interval_gap_count")
    interval_days = _sum(rows, "_interval_total_days")
    total["average_interval_days"] = round(float(interval_days / gaps), 2) if gaps else None
    return [total]


def _health_total(rows):
    if not rows:
        return []
    total = {}
    for section in ("events", "bookings", "machines", "maintenance"):
        enabled_rows = [row for row in rows if row.get(f"{section}_enabled")]
        total[f"{section}_enabled"] = bool(enabled_rows)
        total[f"{section}_available"] = bool(enabled_rows) and all(
            row.get(f"{section}_available") for row in enabled_rows
        )
    additive = (
        "events_in_period", "events_registrations", "events_attended",
        "bookings_active_spaces", "bookings_non_cancelled", "bookings_reserved_hours",
        "bookings_upcoming", "bookings_no_shows", "machines_active",
        "machines_usage_hours", "maintenance_logs", "maintenance_total_cost",
        "maintenance_overdue_schedules",
    )
    for field in additive:
        total[field] = _available_sum(rows, field)
    event_denominator = _sum(rows, "_events_completed_confirmed")
    total["events_completed_attendance_rate_percent"] = _percent(
        _sum(rows, "_events_completed_attended"), event_denominator
    )
    booking_denominator = _sum(rows, "_bookings_window_hours")
    total["bookings_reservation_utilization_percent"] = _percent(
        total["bookings_reserved_hours"], booking_denominator
    )
    return [total]


def _evidence_totals(rows, limit):
    groups = {}
    additive = (
        "created_count", "attached_count", "unattached_count",
        "object_live_count", "object_expired_count", "metadata_retained_count",
        "bytes",
    )
    for row in rows:
        key = (row.get("period"), row.get("evidence_type"))
        target = groups.setdefault(
            key,
            {"period": key[0], "evidence_type": key[1]},
        )
        for field in additive:
            target[field] = target.get(field, 0) + (row.get(field) or 0)
    for total in groups.values():
        total["attachment_rate_percent"] = _percent(
            total["attached_count"], total["created_count"]
        )
    return [
        groups[key]
        for key in sorted(groups, key=lambda item: tuple(str(value or "") for value in item))
    ][:limit]


def _available_sum(rows, field):
    values = [row.get(field) for row in rows if row.get(field) is not None]
    if not values:
        return None
    return sum(values, Decimal("0")) if any(isinstance(value, Decimal) for value in values) else sum(values, 0)


def _decimal_average(numerator, denominator):
    if not denominator:
        return None
    return (Decimal(numerator) / denominator).quantize(CENT, rounding=ROUND_HALF_UP)


def _percent(numerator, denominator):
    if denominator in (None, 0):
        return None
    return round(float(numerator / denominator * 100), 2)


def _ordered_rows(report_key, rows):
    ordering = {
        "taken-items": lambda row: (-row["issued_quantity"], row["product"]),
        "active-loans": lambda row: (_descending_time(row.get("issued_at")), row["id"]),
        "returns": lambda row: (_descending_time(row.get("closed_at")), row["id"]),
        "damaged-missing": lambda row: row["product"],
        "damaged-lost": lambda row: row["product_name"],
        "recently-added": lambda row: (_descending_time(row.get("created_at")), row["product_name"]),
        "machine-usage": lambda row: (-row["usage_hours"], row["machine_name"], row["machine_id"]),
        "most-lent": lambda row: (-row["times_lent"], -row["total_quantity_lent"], row["product_name"]),
    }
    key = ordering.get(report_key)
    return sorted(rows, key=key) if key else rows


def _descending_time(value):
    return -value.timestamp() if value is not None else float("inf")
