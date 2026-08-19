from django.db.models import Count, Q

from apps.events.models import Event, EventOrganizer, EventRegistration
from apps.operations.report_registry import ReportResult
from apps.operations.report_scope import scoped_ids


FIELDS = (
    "event_id", "title", "starts_at", "status", "capacity", "registrations",
    "confirmed", "registered", "waitlisted", "cancelled", "attended",
    "attendance_rate_percent", "organizers",
)


def build_event_attendance(makerspace_id, *, limit=None, date_range=None):
    aggregate = makerspace_id is None
    queryset = Event.objects.filter(
        makerspace_id__in=scoped_ids(makerspace_id, "events")
    )
    if date_range:
        start, end = date_range
        if start is not None:
            queryset = queryset.filter(starts_at__gte=start)
        if end is not None:
            queryset = queryset.filter(starts_at__lt=end)
    statuses = EventRegistration.Status
    queryset = queryset.values(
        "id", "makerspace_id", "title", "starts_at", "status", "capacity"
    ).annotate(
        total=Count("registrations"),
        registered_count=Count("registrations", filter=Q(registrations__status=statuses.REGISTERED)),
        waitlisted_count=Count("registrations", filter=Q(registrations__status=statuses.WAITLISTED)),
        cancelled_count=Count("registrations", filter=Q(registrations__status=statuses.CANCELLED)),
        attended_count=Count("registrations", filter=Q(registrations__status=statuses.ATTENDED)),
    )
    ordering = ("makerspace_id", "-starts_at", "id") if aggregate else ("-starts_at", "id")
    rows = list(queryset.order_by(*ordering)[:limit] if limit is not None else queryset.order_by(*ordering))
    organizers_by_event = {}
    organizer_rows = EventOrganizer.objects.filter(
        event_id__in=[row["id"] for row in rows]
    ).values("event_id", "organization__slug", "organization__name").order_by(
        "organization__name", "organization_id"
    )
    for organizer in organizer_rows:
        organizers_by_event.setdefault(organizer["event_id"], []).append(
            f'{organizer["organization__name"]} '
            f'({organizer["organization__slug"]})'
        )
    fields = (("makerspace_id",) + FIELDS) if aggregate else FIELDS
    records = []
    for row in rows:
        denominator = row["registered_count"] + row["attended_count"]
        rate = None
        if row["status"] == Event.Status.COMPLETED and denominator:
            rate = round(row["attended_count"] / denominator * 100, 2)
        record = {
            "event_id": row["id"], "title": row["title"],
            "starts_at": row["starts_at"], "status": row["status"],
            "capacity": row["capacity"], "registrations": row["total"],
            "confirmed": denominator, "registered": row["registered_count"],
            "waitlisted": row["waitlisted_count"], "cancelled": row["cancelled_count"],
            "attended": row["attended_count"], "attendance_rate_percent": rate,
            "organizers": "; ".join(organizers_by_event.get(row["id"], [])),
        }
        if aggregate:
            record["makerspace_id"] = row["makerspace_id"]
        records.append(record)
    return ReportResult(fields, records)
