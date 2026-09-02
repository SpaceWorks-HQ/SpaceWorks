from datetime import date, datetime, timedelta, timezone as dt_timezone
from zoneinfo import ZoneInfo

from django.db.models import F
from django.utils import timezone

from apps.events.models import Event, EventRegistration, EventSeries
from apps.events.services_recurrence import local_anchor


CALENDAR_EVENT_FIELDS = frozenset({
    "title", "description", "starts_at", "ends_at", "location", "timezone_name", "is_public",
})
CALENDAR_SERIES_FIELDS = frozenset({
    "title", "description", "location", "recurrence_timezone", "dtstart_local_date",
    "dtstart_local_time", "recurrence_rule", "duration_minutes", "is_public",
})


def calendar_event_changed(event, *, now=None):
    now = now or timezone.now()
    Event.objects.filter(pk=event.pk).update(
        calendar_sequence=F("calendar_sequence") + 1,
        calendar_updated_at=now,
    )
    event.refresh_from_db(fields=("calendar_sequence", "calendar_updated_at"))
    return event


def calendar_registration_changed(registration, *, now=None):
    now = now or timezone.now()
    EventRegistration.objects.filter(pk=registration.pk).update(
        calendar_sequence=F("calendar_sequence") + 1,
        calendar_updated_at=now,
    )
    registration.refresh_from_db(fields=("calendar_sequence", "calendar_updated_at"))
    return registration


def calendar_series_changed(series, *, now=None):
    now = now or timezone.now()
    EventSeries.objects.filter(pk=series.pk).update(
        calendar_sequence=F("calendar_sequence") + 1,
        calendar_updated_at=now,
    )
    series.refresh_from_db(fields=("calendar_sequence", "calendar_updated_at"))
    return series


def _icalendar_types():
    from icalendar import Calendar, Event as ICalEvent, Timezone, vRecur

    return Calendar, ICalEvent, Timezone, vRecur


def _calendar(name, *, method="PUBLISH"):
    Calendar, _ICalEvent, _Timezone, _vRecur = _icalendar_types()
    calendar = Calendar()
    calendar.add("prodid", "-//SpaceWorks//Events//EN")
    calendar.add("version", "2.0")
    calendar.add("calscale", "GREGORIAN")
    calendar.add("method", method)
    calendar.add("x-wr-calname", name)
    return calendar


def _utc(value):
    return value.astimezone(dt_timezone.utc)


def _add_common(component, *, uid, title, description, location, starts_at,
                ends_at, status, sequence, updated_at):
    component.add("uid", uid)
    component.add("summary", title)
    if description:
        component.add("description", description)
    if location:
        component.add("location", location)
    component.add("dtstart", starts_at)
    component.add("dtend", ends_at)
    component.add("dtstamp", _utc(updated_at))
    component.add("last-modified", _utc(updated_at))
    component.add("status", status)
    component.add("sequence", sequence)


def _event_component(event, *, registration=None):
    _Calendar, ICalEvent, _Timezone, _vRecur = _icalendar_types()
    component = ICalEvent()
    status = "CONFIRMED"
    sequence = event.calendar_sequence
    description = event.description
    if event.status == Event.Status.CANCELLED:
        status = "CANCELLED"
    if registration is not None:
        sequence += registration.calendar_sequence
        updated = max(event.calendar_updated_at, registration.calendar_updated_at)
        if event.status == Event.Status.CANCELLED:
            status = "CANCELLED"
        elif registration.status in (
            EventRegistration.Status.PENDING_APPROVAL,
            EventRegistration.Status.WAITLISTED,
        ):
            status = "TENTATIVE"
        elif registration.status in (
            EventRegistration.Status.REJECTED,
            EventRegistration.Status.CANCELLED,
        ):
            status = "CANCELLED"
        state = registration.get_status_display()
        description = f"Registration status: {state}." + (
            f"\n\n{event.description}" if event.description else ""
        )
    else:
        updated = event.calendar_updated_at
    _add_common(
        component,
        uid=f"event-{event.calendar_uid}@spaceworks",
        title=event.title,
        description=description,
        location=event.location,
        starts_at=_utc(event.starts_at),
        ends_at=_utc(event.ends_at),
        status=status,
        sequence=sequence,
        updated_at=updated,
    )
    return component


def render_public_event_calendar(event):
    if event.series_id and event.series.is_public:
        return render_public_series_calendar(event.series)
    method = "CANCEL" if event.status == Event.Status.CANCELLED else "PUBLISH"
    calendar = _calendar(event.title, method=method)
    calendar.add_component(_event_component(event))
    return calendar.to_ical()


def _series_local_start(series):
    return local_anchor(
        local_date=series.dtstart_local_date,
        local_time=series.dtstart_local_time,
        timezone_name=series.recurrence_timezone,
    )


def _add_vtimezone(calendar, series):
    _Calendar, _ICalEvent, Timezone, _vRecur = _icalendar_types()
    zone = ZoneInfo(series.recurrence_timezone)
    first = series.dtstart_local_date - timedelta(days=366)
    # Unbounded RRULEs outlive the currently materialized occurrence window. Carry a
    # long transition horizon so calendar clients do not silently freeze DST rules at
    # the library's historical 2038 default.
    last = first + timedelta(days=366 * 50)
    calendar.add_component(
        Timezone.from_tzinfo(zone, tzid=series.recurrence_timezone,
                             first_date=first, last_date=last)
    )


def _series_exception(series, event):
    _Calendar, ICalEvent, _Timezone, _vRecur = _icalendar_types()
    component = ICalEvent()
    local_text = event.series_occurrence_key.split(":", 1)[1]
    recurrence_id = datetime.strptime(local_text, "%Y%m%dT%H%M%S").replace(
        tzinfo=ZoneInfo(series.recurrence_timezone), fold=0
    )
    hidden = not event.is_public
    status = "CANCELLED" if event.status == Event.Status.CANCELLED or hidden else "CONFIRMED"
    _add_common(
        component,
        uid=f"event-series-{series.calendar_uid}@spaceworks",
        # A private exception still has to cancel the public RRULE instance, but its
        # private title/location/moved time must not hitchhike into the public feed.
        title=series.title if hidden else event.title,
        description=series.description if hidden else event.description,
        location=series.location if hidden else event.location,
        starts_at=recurrence_id if hidden else _utc(event.starts_at),
        ends_at=(
            recurrence_id + timedelta(minutes=series.duration_minutes)
            if hidden else _utc(event.ends_at)
        ),
        status=status,
        sequence=series.calendar_sequence + event.calendar_sequence,
        updated_at=max(series.calendar_updated_at, event.calendar_updated_at),
    )
    component.add("recurrence-id", recurrence_id)
    return component


def render_public_series_calendar(series):
    _Calendar, ICalEvent, _Timezone, vRecur = _icalendar_types()
    method = "CANCEL" if series.status == EventSeries.Status.CANCELLED else "PUBLISH"
    calendar = _calendar(series.title, method=method)
    _add_vtimezone(calendar, series)
    master = ICalEvent()
    start = _series_local_start(series)
    status = "CANCELLED" if series.status == EventSeries.Status.CANCELLED else "CONFIRMED"
    _add_common(
        master,
        uid=f"event-series-{series.calendar_uid}@spaceworks",
        title=series.title,
        description=series.description,
        location=series.location,
        starts_at=start,
        ends_at=start + timedelta(minutes=series.duration_minutes),
        status=status,
        sequence=series.calendar_sequence,
        updated_at=series.calendar_updated_at,
    )
    master.add("rrule", vRecur.from_ical(series.recurrence_rule))
    calendar.add_component(master)
    exceptions = series.occurrences.filter(series_revision=series.revision).exclude(
        series_override_fields=[]
    ) | series.occurrences.filter(
        series_revision=series.revision,
        status=Event.Status.CANCELLED,
    ) | series.occurrences.filter(
        series_revision=series.revision,
        is_public=False,
    )
    for event in exceptions.distinct().order_by("starts_at", "pk"):
        calendar.add_component(_series_exception(series, event))
    return calendar.to_ical()


def render_member_calendar(makerspace, registrations):
    calendar = _calendar(f"{makerspace.name} - My events")
    for registration in registrations.select_related("event").order_by(
        "event__starts_at", "pk"
    ):
        calendar.add_component(
            _event_component(registration.event, registration=registration)
        )
    return calendar.to_ical()
