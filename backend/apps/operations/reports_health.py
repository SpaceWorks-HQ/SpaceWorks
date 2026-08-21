import logging
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from django.apps import apps
from django.db.models import Count, DecimalField, DurationField, ExpressionWrapper, F, OuterRef, Q, Subquery, Sum, Value
from django.db.models.functions import Coalesce, Greatest, Least
from django.utils import timezone

from apps.makerspaces.models import Makerspace
from apps.operations.report_registry import ReportResult
from apps.operations.report_scope import eligible_makerspaces
from apps.separability.registry import runtime_active


logger = logging.getLogger(__name__)
CENT = Decimal("0.01")
FIELDS = (
    "events_enabled", "events_available", "events_in_period", "events_registrations", "events_attended", "events_completed_attendance_rate_percent",
    "bookings_enabled", "bookings_available", "bookings_active_spaces", "bookings_non_cancelled", "bookings_reserved_hours", "bookings_upcoming", "bookings_no_shows", "bookings_reservation_utilization_percent",
    "machines_enabled", "machines_available", "machines_active", "machines_usage_hours",
    "maintenance_enabled", "maintenance_available", "maintenance_logs", "maintenance_total_cost", "maintenance_overdue_schedules",
)
SECTION_FIELDS = {
    "events": FIELDS[2:6], "bookings": FIELDS[8:14],
    "machines": FIELDS[16:18], "maintenance": FIELDS[20:23],
}


def build_fablab_health(makerspace_id, *, limit=None, date_range=None):
    aggregate = makerspace_id is None
    now = timezone.now()
    today = timezone.localdate()
    base = eligible_makerspaces() if aggregate else Makerspace.objects.filter(pk=makerspace_id)
    spaces = list(base.values("id", "enabled_modules").order_by("id"))
    records = {row["id"]: _empty_record(row, aggregate) for row in spaces}
    _run_section(spaces, records, "events", lambda ids: _event_rows(ids, date_range))
    _run_section(spaces, records, "bookings", lambda ids: _booking_rows(ids, date_range, now))
    _run_section(spaces, records, "machines", lambda ids: _machine_rows(ids, date_range))
    _run_section(spaces, records, "maintenance", lambda ids: _maintenance_rows(ids, date_range, today))
    ordered = [records[row["id"]] for row in spaces]
    if limit is not None:
        ordered = ordered[:limit]
    return ReportResult((("makerspace_id",) + FIELDS) if aggregate else FIELDS, ordered)


def _empty_record(space, aggregate):
    record = {}
    modules = set(space["enabled_modules"] or [])
    for section, metrics in SECTION_FIELDS.items():
        enabled = runtime_active(section) and section in modules
        record[f"{section}_enabled"] = enabled
        record[f"{section}_available"] = False
        record.update({metric: None for metric in metrics})
    if aggregate:
        record["makerspace_id"] = space["id"]
    return record


def _run_section(spaces, records, section, build_rows):
    enabled_ids = [row["id"] for row in spaces if records[row["id"]][f"{section}_enabled"]]
    if not enabled_ids:
        return
    try:
        materialized = list(build_rows(enabled_ids))
        for makerspace_id in enabled_ids:
            records[makerspace_id][f"{section}_available"] = True
            records[makerspace_id].update(_zero_values(section))
        for row in materialized:
            makerspace_id = row.pop("makerspace_id")
            records[makerspace_id].update(row)
    except Exception:
        logger.exception("FabLab health %s section unavailable", section)


def _zero_values(section):
    values = {field: 0 for field in SECTION_FIELDS[section]}
    if section == "events":
        values["events_completed_attendance_rate_percent"] = None
        values["_events_completed_attended"] = 0
        values["_events_completed_confirmed"] = 0
    if section == "bookings":
        values["bookings_reserved_hours"] = Decimal("0.00")
        values["bookings_reservation_utilization_percent"] = None
        values["_bookings_window_hours"] = None
    if section == "machines":
        values["machines_usage_hours"] = Decimal("0.00")
    if section == "maintenance":
        values["maintenance_total_cost"] = Decimal("0.00")
    return values


def _event_rows(ids, date_range):
    from apps.events.models import Event, EventRegistration

    period = _period_q("events__starts_at", date_range)
    completed = period & Q(events__status=Event.Status.COMPLETED)
    attended = Q(events__registrations__status=EventRegistration.Status.ATTENDED)
    registered = Q(events__registrations__status=EventRegistration.Status.REGISTERED)
    rows = list(Makerspace.objects.filter(id__in=ids).values("id").annotate(
        events=Count("events", filter=period, distinct=True),
        registrations=Count("events__registrations", filter=period),
        attended=Count("events__registrations", filter=period & attended),
        completed_attended=Count("events__registrations", filter=completed & attended),
        completed_registered=Count("events__registrations", filter=completed & registered),
    ))
    result = []
    for row in rows:
        denominator = row["completed_attended"] + row["completed_registered"]
        result.append({
            "makerspace_id": row["id"], "events_in_period": row["events"],
            "events_registrations": row["registrations"], "events_attended": row["attended"],
            "events_completed_attendance_rate_percent": round(row["completed_attended"] / denominator * 100, 2) if denominator else None,
            # Private inputs are retained in ReportResult.records but omitted from
            # FIELDS, so legacy single-space responses and exports do not change.
            "_events_completed_attended": row["completed_attended"],
            "_events_completed_confirmed": denominator,
        })
    return result


def _booking_rows(ids, date_range, now):
    from apps.bookings.models import Booking

    path = "bookable_spaces__bookings"
    start = end = None
    overlap = Q()
    if date_range:
        start, end = date_range
        if start:
            overlap &= Q(**{f"{path}__ends_at__gt": start})
        if end:
            overlap &= Q(**{f"{path}__starts_at__lt": end})
    clipped_start = Greatest(F(f"{path}__starts_at"), Value(start)) if start else F(f"{path}__starts_at")
    clipped_end = Least(F(f"{path}__ends_at"), Value(end)) if end else F(f"{path}__ends_at")
    duration = ExpressionWrapper(clipped_end - clipped_start, output_field=DurationField())
    active = (
        Booking.Status.CONFIRMED,
        Booking.Status.COMPLETED,
        Booking.Status.NO_SHOW,
    )
    rows = list(Makerspace.objects.filter(id__in=ids).values("id").annotate(
        spaces=Count("bookable_spaces", filter=Q(bookable_spaces__is_active=True), distinct=True),
        bookings=Count(path, filter=overlap & Q(**{f"{path}__status__in": active})),
        reserved=Sum(duration, filter=overlap & Q(**{f"{path}__status__in": active})),
        upcoming=Count(path, filter=overlap & Q(**{f"{path}__status": Booking.Status.CONFIRMED, f"{path}__starts_at__gte": now})),
        no_shows=Count(path, filter=overlap & Q(**{f"{path}__status": Booking.Status.NO_SHOW})),
    ))
    window = _hours(end - start) if start and end else None
    result = []
    for row in rows:
        reserved = _hours(row["reserved"] or timedelta())
        result.append({
            "makerspace_id": row["id"], "bookings_active_spaces": row["spaces"],
            "bookings_non_cancelled": row["bookings"], "bookings_reserved_hours": reserved,
            "bookings_upcoming": row["upcoming"], "bookings_no_shows": row["no_shows"],
            "bookings_reservation_utilization_percent": round(float(reserved / window * 100), 2) if window else None,
            "_bookings_window_hours": window,
        })
    return result


def _machine_rows(ids, date_range):
    period = _period_q("machines__usage_entries__created_at", date_range)
    rows = list(Makerspace.objects.filter(id__in=ids).values("id").annotate(
        active=Count("machines", filter=Q(machines__is_active=True), distinct=True),
        hours=Coalesce(Sum("machines__usage_entries__hours", filter=period), Value(Decimal("0.00")), output_field=DecimalField(max_digits=20, decimal_places=2)),
    ))
    return [{"makerspace_id": row["id"], "machines_active": row["active"], "machines_usage_hours": row["hours"]} for row in rows]


def _maintenance_rows(ids, date_range, today):
    from apps.maintenance.models import MaintenanceLog, MaintenanceSchedule

    period = _period_q("performed_at", date_range)
    logs = MaintenanceLog.objects.filter(machine__makerspace_id=OuterRef("pk")).filter(period).values("machine__makerspace_id").annotate(count=Count("id"), total=Sum("cost"))
    schedules = MaintenanceSchedule.objects.filter(machine__makerspace_id=OuterRef("pk"), is_active=True, next_due__lt=today).values("machine__makerspace_id").annotate(count=Count("id"))
    rows = list(Makerspace.objects.filter(id__in=ids).values("id").annotate(
        logs=Coalesce(Subquery(logs.values("count")[:1]), Value(0)),
        cost=Coalesce(Subquery(logs.values("total")[:1], output_field=DecimalField(max_digits=20, decimal_places=2)), Value(Decimal("0.00"))),
        overdue=Coalesce(Subquery(schedules.values("count")[:1]), Value(0)),
    ))
    return [{"makerspace_id": row["id"], "maintenance_logs": row["logs"], "maintenance_total_cost": row["cost"], "maintenance_overdue_schedules": row["overdue"]} for row in rows]


def _period_q(field, date_range):
    query = Q()
    if date_range:
        start, end = date_range
        if start:
            query &= Q(**{f"{field}__gte": start})
        if end:
            query &= Q(**{f"{field}__lt": end})
    return query


def _hours(value):
    micros = ((value.days * 86400 + value.seconds) * 1_000_000) + value.microseconds
    return (Decimal(micros) / Decimal(3_600_000_000)).quantize(CENT, rounding=ROUND_HALF_UP)
