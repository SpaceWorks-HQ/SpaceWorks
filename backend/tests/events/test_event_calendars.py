from datetime import time, timedelta

import pytest
from django.urls import reverse
from django.utils import timezone
from drf_spectacular.generators import SchemaGenerator
from icalendar import Calendar
from rest_framework.test import APIClient

from apps.events import services
from apps.events.models import Event, EventRegistration, EventSeries
from tests.events.checkin_helpers import (
    client_for, make_event, make_member, make_space, make_staff, register,
)


pytestmark = pytest.mark.django_db


def public_url(space, event):
    return reverse("public-event-calendar", kwargs={
        "makerspace_slug": space.slug, "public_token": event.public_token,
    })


def event_components(response):
    return [row for row in Calendar.from_ical(response.content).walk() if row.name == "VEVENT"]


def test_public_calendar_has_stable_uid_sequence_and_no_registration_pii():
    space = make_space("calendar-public")
    event = make_event(space, title="Safe workshop", description="Public description")
    staff = make_staff(space, "calendar-public-staff")
    member = make_member(space, "calendar-public-member", display_name="Private Person")
    register(event, member, email="private-calendar@example.test")
    first = APIClient().get(public_url(space, event))
    component = event_components(first)[0]

    services.update_event(event, actor=staff, location="New room")
    second = APIClient().get(public_url(space, event))
    changed = event_components(second)[0]

    assert first.status_code == second.status_code == 200
    assert component["uid"] == changed["uid"] == f"event-{event.calendar_uid}@spaceworks"
    assert int(changed["sequence"]) == int(component["sequence"]) + 1
    assert changed["location"] == "New room"
    assert b"Private Person" not in second.content
    assert b"private-calendar@example.test" not in second.content
    assert second["Content-Type"].startswith("text/calendar")


def test_public_calendar_is_module_gated_on_both_sides():
    space = make_space("calendar-module")
    event = make_event(space)
    assert APIClient().get(public_url(space, event)).status_code == 200

    space.enabled_modules = [key for key in space.enabled_modules if key != "events"]
    space.save(update_fields=("enabled_modules",))
    assert APIClient().get(public_url(space, event)).status_code == 400


def test_member_calendar_is_private_and_scoped_to_the_authenticated_member():
    space = make_space("calendar-member")
    mine = make_member(space, "calendar-mine", display_name="Mine")
    other = make_member(space, "calendar-other", display_name="Other")
    own_registration = register(make_event(space, "My private title", is_public=False), mine)
    register(make_event(space, "Someone else's title"), other)
    response = client_for(mine).get(reverse(
        "member-event-calendar", kwargs={"makerspace_id": space.pk},
    ))
    component = event_components(response)[0]

    assert response.status_code == 200
    assert response["Cache-Control"].startswith("private")
    assert component["uid"] == f"event-{own_registration.event.calendar_uid}@spaceworks"
    assert "Registration status: Registered" in str(component["description"])
    assert b"Someone else's title" not in response.content
    assert str(own_registration.checkin_token).encode() not in response.content
    assert APIClient().get(response.request["PATH_INFO"]).status_code in (401, 403)


def test_event_cancellation_overrides_a_waitlisted_registration_to_cancelled():
    space = make_space("calendar-cancelled-waitlist")
    member = make_member(space, "calendar-cancelled-member")
    event = make_event(space, status=Event.Status.CANCELLED)
    register(event, member, status=EventRegistration.Status.WAITLISTED)
    response = client_for(member).get(reverse(
        "member-event-calendar", kwargs={"makerspace_id": space.pk},
    ))
    assert str(event_components(response)[0]["status"]) == "CANCELLED"


def test_series_calendar_uses_one_rrule_uid_with_override_exceptions():
    space = make_space("calendar-series")
    tomorrow = (timezone.now() + timedelta(days=1)).date()
    series = EventSeries.objects.create(
        makerspace=space, title="Weekly studio", description="Series description",
        recurrence_timezone="Asia/Kolkata", dtstart_local_date=tomorrow,
        dtstart_local_time=time(18, 30), recurrence_rule="FREQ=WEEKLY;COUNT=3",
        duration_minutes=60, is_public=True, status=EventSeries.Status.PUBLISHED,
    )
    start = timezone.now() + timedelta(days=1)
    event = Event.objects.create(
        makerspace=space, series=series, series_occurrence_key=f"local:{tomorrow:%Y%m%d}T183000",
        series_revision=series.revision, series_override_fields=["location"],
        title=series.title, description=series.description, location="Special room",
        starts_at=start, ends_at=start + timedelta(hours=1), timezone_name="Asia/Kolkata",
        is_public=True, status=Event.Status.PUBLISHED,
    )
    hidden_date = tomorrow + timedelta(days=7)
    Event.objects.create(
        makerspace=space, series=series,
        series_occurrence_key=f"local:{hidden_date:%Y%m%d}T183000",
        series_revision=series.revision, series_override_fields=["title", "is_public"],
        title="Private planning sentinel", description="Do not publish", location="Secret room",
        starts_at=start + timedelta(days=7), ends_at=start + timedelta(days=7, hours=1),
        timezone_name="Asia/Kolkata", is_public=False, status=Event.Status.PUBLISHED,
    )
    response = APIClient().get(public_url(space, event))
    components = event_components(response)

    assert response.status_code == 200
    assert len(components) == 3
    assert components[0]["rrule"]["FREQ"] == ["WEEKLY"]
    assert components[0]["uid"] == components[1]["uid"]
    assert components[1]["recurrence-id"] is not None
    assert b"TZID:Asia/Kolkata" in response.content
    assert b"Private planning sentinel" not in response.content
    hidden_component = next(row for row in components if str(row["status"]) == "CANCELLED")
    assert hidden_component["summary"] == series.title


def test_calendar_and_badge_openapi_operations_declare_binary_responses():
    schema = SchemaGenerator().get_schema(request=None, public=True)
    operations = {
        "/api/v1/public/{makerspace_slug}/events/{public_token}/calendar.ics": ("get", "text/calendar"),
        "/api/v1/member/makerspaces/{makerspace_id}/event-registrations/calendar.ics": ("get", "text/calendar"),
        "/api/v1/public/{makerspace_slug}/event-calendar/{raw_token}.ics": ("get", "text/calendar"),
        "/api/v1/admin/events/{id}/badges.pdf": ("post", "application/pdf"),
    }
    for path, (method, media_type) in operations.items():
        assert media_type in schema["paths"][path][method]["responses"]["200"]["content"]
    feed = schema["paths"][
        "/api/v1/member/makerspaces/{makerspace_id}/event-calendar-feed/"
    ]
    assert {"get", "post", "delete"} <= set(feed)
    assert {"get", "put"} <= set(schema["paths"][
        "/api/v1/admin/events/{id}/badge-template/"
    ])
