"""Declarative organization aggregation contract for every supported report."""

from dataclasses import dataclass
from enum import Enum


class AggregationKind(str, Enum):
    SUM = "sum"
    GROUP_SUM = "group_sum"
    ROW_UNION = "row_union"
    WEIGHTED_RATE = "weighted_rate"
    GLOBAL_RANK = "global_rank"
    DISTINCT_PERSON = "distinct_person"


class LimitSemantics(str, Enum):
    # Every breakdown is limited independently. These values declare whether the
    # combined total sees all source rows or only each space's already-limited top K.
    GLOBAL_AFTER_AGGREGATION = "global_after_aggregation"
    PER_SPACE_THEN_GLOBAL = "per_space_then_global"


@dataclass(frozen=True)
class OrganizationAggregationStrategy:
    kind: AggregationKind
    grouping_keys: tuple[str, ...]
    total_fields: tuple[str, ...]
    breakdown_only_fields: tuple[str, ...]
    ordering: tuple[str, ...]
    limit_semantics: LimitSemantics = LimitSemantics.GLOBAL_AFTER_AGGREGATION
    non_numeric_treatment: tuple[tuple[str, str], ...] = ()


SUMMARY_FIELDS = (
    "products", "assets", "active_loans", "available_quantity",
    "issued_quantity", "damaged_quantity", "missing_quantity",
)


def _strategy(kind, groups, totals, *, breakdown=(), ordering=(), limit=None, text=()):
    return OrganizationAggregationStrategy(
        kind=kind,
        grouping_keys=groups,
        total_fields=totals,
        breakdown_only_fields=breakdown,
        ordering=ordering,
        limit_semantics=limit or LimitSemantics.GLOBAL_AFTER_AGGREGATION,
        non_numeric_treatment=text,
    )


STRATEGIES = {
    "summary": _strategy(AggregationKind.SUM, (), SUMMARY_FIELDS),
    "taken-items": _strategy(
        AggregationKind.GROUP_SUM, ("product_id",), ("product", "issued_quantity"),
        ordering=("-issued_quantity", "product"), text=(("product", "carry display label; distinct products are never merged by name"),),
    ),
    "active-loans": _strategy(
        AggregationKind.GROUP_SUM, ("request_id",), ("id", "requester", "status", "issued_at"),
        ordering=("-issued_at", "id"),
        text=(("requester", "carry"), ("status", "carry"), ("issued_at", "carry and order descending")),
    ),
    "returns": _strategy(
        AggregationKind.GROUP_SUM, ("request_id",), ("id", "requester", "status", "closed_at"),
        ordering=("-closed_at", "id"),
        text=(("requester", "carry"), ("status", "carry"), ("closed_at", "carry and order descending")),
    ),
    "damaged-missing": _strategy(
        AggregationKind.GROUP_SUM, ("product_id",), ("product", "damaged_quantity", "missing_quantity"),
        ordering=("product",), text=(("product", "carry; distinct products are never merged by name"),),
    ),
    "damaged-lost": _strategy(
        AggregationKind.GROUP_SUM, ("product_id",), ("product_name", "damaged_quantity", "lost_quantity"),
        ordering=("product_name",), text=(("product_name", "carry; distinct products are never merged by name"),),
    ),
    "qr-scans": _strategy(
        AggregationKind.GROUP_SUM, ("context",), ("context", "count"),
        ordering=("context",), text=(("context", "group and carry"),),
    ),
    "recently-added": _strategy(
        AggregationKind.GROUP_SUM, ("product_id",), ("product_name", "created_at", "total_quantity"),
        ordering=("-created_at", "product_name"),
        text=(("product_name", "carry"), ("created_at", "carry and order descending")),
    ),
    "machine-usage": _strategy(
        AggregationKind.GROUP_SUM, ("machine_id",),
        ("machine_id", "machine_name", "machine_type", "is_active", "usage_entries", "usage_hours"),
        ordering=("-usage_hours", "machine_name", "machine_id"),
        text=(("machine_name", "carry"), ("machine_type", "carry"), ("is_active", "carry")),
    ),
    "payment-reconciliation": _strategy(
        AggregationKind.GROUP_SUM, ("currency", "subject_type", "status"),
        ("currency", "subject_type", "status", "payment_count", "amount_total", "outstanding_amount"),
        ordering=("currency", "subject_type", "status"),
        text=(("currency", "group and carry"), ("subject_type", "group and carry"), ("status", "group and carry")),
    ),
    "most-lent": _strategy(
        AggregationKind.ROW_UNION, ("product_id",),
        ("product_name", "times_lent", "total_quantity_lent"),
        ordering=("-times_lent", "-total_quantity_lent", "product_name"),
        limit=LimitSemantics.PER_SPACE_THEN_GLOBAL,
        text=(("product_name", "carry; products remain distinct even when labels match"),),
    ),
    "top-borrowers": _strategy(
        AggregationKind.GLOBAL_RANK, ("requester_id",), ("holder", "requests", "items_borrowed"),
        ordering=("-requests", "-items_borrowed", "requester_id"),
        text=(("holder", "label from newest qualifying request after global regrouping"),),
    ),
    "member-activity": _strategy(
        AggregationKind.DISTINCT_PERSON, ("user_id",),
        ("new_members", "active_members", "revoked_members", "pending_requests", "open_invites", "referred_joins", "verified_members"),
        breakdown=("makerspace_name", "membership_policy", "referrals_enabled"),
        ordering=(), text=(("makerspace_name", "breakdown-only"), ("membership_policy", "breakdown-only"), ("referrals_enabled", "breakdown-only")),
    ),
    "event-attendance": _strategy(
        AggregationKind.WEIGHTED_RATE, (),
        ("capacity", "registrations", "confirmed", "pending_approval", "registered", "waitlisted", "rejected", "cancelled", "attended", "attendance_rate_percent"),
        breakdown=("event_id", "title", "starts_at", "status", "organizers"),
        ordering=(), text=(
            ("title", "breakdown-only"), ("starts_at", "breakdown-only"),
            ("status", "breakdown-only"), ("organizers", "breakdown-only"),
        ),
    ),
    "booking-utilization": _strategy(
        AggregationKind.WEIGHTED_RATE, (),
        ("booked", "completed", "no_show", "cancelled", "upcoming", "reserved_hours", "completed_hours", "window_hours", "reservation_utilization_percent", "no_show_rate_percent"),
        breakdown=("space_id", "space_name", "kind", "is_active"), ordering=(),
        text=(("space_name", "breakdown-only"), ("kind", "breakdown-only"), ("is_active", "breakdown-only")),
    ),
    "maintenance-activity": _strategy(
        AggregationKind.WEIGHTED_RATE, (),
        ("log_count", "costed_log_count", "total_cost", "average_cost", "last_performed_at", "average_interval_days", "active_schedules", "overdue_schedules"),
        breakdown=("machine_id", "machine_name", "machine_type", "is_active"), ordering=(),
        text=(("machine_name", "breakdown-only"), ("machine_type", "breakdown-only"), ("is_active", "breakdown-only"), ("last_performed_at", "latest value survives")),
    ),
    "fablab-health": _strategy(
        AggregationKind.WEIGHTED_RATE, (),
        (
            "events_enabled", "events_available", "events_in_period", "events_registrations", "events_attended", "events_completed_attendance_rate_percent",
            "bookings_enabled", "bookings_available", "bookings_active_spaces", "bookings_non_cancelled", "bookings_reserved_hours", "bookings_upcoming", "bookings_no_shows", "bookings_reservation_utilization_percent",
            "machines_enabled", "machines_available", "machines_active", "machines_usage_hours",
            "maintenance_enabled", "maintenance_available", "maintenance_logs", "maintenance_total_cost", "maintenance_overdue_schedules",
        ), ordering=(),
        text=(("*_enabled", "ANY"), ("*_available", "ALL among enabled makerspaces; false when none enabled")),
    ),
}


def organization_strategy(report_key: str) -> OrganizationAggregationStrategy:
    try:
        return STRATEGIES[report_key]
    except KeyError as exc:
        raise ValueError(f"Report {report_key!r} has no organization aggregation strategy.") from exc
