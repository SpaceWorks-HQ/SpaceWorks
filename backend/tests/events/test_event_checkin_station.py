from datetime import timedelta
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet
from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.events.checkin_tokens import read_lease
from apps.events.models import EventCheckInEvent, EventCheckInStationCredential
from apps.events.services_checkin_roster import issue_roster
from apps.events.services_checkin_sync import synchronize
from tests.events.checkin_helpers import (
    client_for,
    make_event,
    make_member,
    make_space,
    make_staff,
    register,
)

pytestmark = pytest.mark.django_db
ORIGIN = "http://localhost:5000"
STATION_HEADERS = {"HTTP_ORIGIN": ORIGIN, "HTTP_X_STATION_CSRF": "present"}


@pytest.fixture(autouse=True)
def station_settings(settings):
    settings.API_CLIENT_ENC_KEY = Fernet.generate_key().decode("ascii")
    settings.EVENT_STATION_PIN_PEPPER = "test-only-independent-station-pepper"
    # The PIN exchange requires an exact allowed Origin, so the station origin has to be
    # registered or every SUCCESS path fails the CSRF gate -- and the 403-expecting tests
    # would still pass, for the wrong reason.
    settings.CORS_ALLOWED_ORIGINS = [ORIGIN]
    cache.clear()
    yield
    cache.clear()


def enable_offline(space):
    space.enabled_features = [*space.enabled_features, "events.offline_checkin"]
    space.save(update_fields=["enabled_features"])


def rotate_url(event):
    return reverse("admin-event-check-in-station-rotate", kwargs={"pk": event.pk})


def station_url(name, public_token):
    return reverse(name, kwargs={"public_token": public_token})


def rotate_station(event, staff):
    response = client_for(staff).post(rotate_url(event), {}, format="json")
    assert response.status_code == 200
    assert response["Cache-Control"] == "private, no-store"
    return response.data


def start_station(payload):
    client = APIClient()
    response = client.post(
        station_url("event-check-in-station-session", payload["public_token"]),
        {"pin": payload["pin"]},
        format="json",
        **STATION_HEADERS,
    )
    return client, response


def test_station_controls_are_feature_gated_on_both_sides():
    space = make_space()
    event = make_event(space)
    staff = make_staff(space)

    assert client_for(staff).post(rotate_url(event), {}, format="json").status_code == 400
    assert not EventCheckInStationCredential.objects.exists()

    enable_offline(space)
    payload = rotate_station(event, staff)
    assert payload["pin"].isdigit() and len(payload["pin"]) == 8
    space.enabled_features = [
        key for key in space.enabled_features if key != "events.offline_checkin"
    ]
    space.save(update_fields=["enabled_features"])
    _station, rejected = start_station(payload)
    assert rejected.status_code == 403
    assert not EventCheckInEvent.objects.exists()


def test_pin_is_hashed_encrypted_rotatable_and_reveal_is_step_up_audited():
    space = make_space()
    enable_offline(space)
    event = make_event(space)
    staff = make_staff(space)
    staff.set_password("correct horse battery staple")
    staff.save(update_fields=["password"])

    first = rotate_station(event, staff)
    credential = EventCheckInStationCredential.objects.get(event=event)
    assert first["pin"] not in credential.pin_digest
    assert first["pin"].encode() not in bytes(credential.pin_ciphertext)

    revealed = client_for(staff).post(
        reverse("admin-event-check-in-station-reveal", kwargs={"pk": event.pk}),
        {"current_password": "correct horse battery staple"},
        format="json",
    )
    assert revealed.status_code == 200
    assert revealed["Cache-Control"] == "private, no-store"
    assert revealed.data["pin"] == first["pin"]

    second = rotate_station(event, staff)
    credential.refresh_from_db()
    assert second["pin"] != first["pin"]
    assert credential.version == 2
    assert first["pin"] not in str(
        list(AuditLog.objects.filter(makerspace=space).values_list("meta", flat=True))
    )
    assert AuditLog.objects.filter(action="event.station_pin_revealed").exists()


def test_station_session_cookie_is_scoped_and_rotation_invalidates_it(settings):
    settings.AUTH_COOKIE_SECURE = True
    space = make_space()
    enable_offline(space)
    event = make_event(space)
    staff = make_staff(space)
    first = rotate_station(event, staff)
    station, response = start_station(first)

    assert response.status_code == 204
    cookie = response.cookies["sw_event_station"]
    assert cookie["httponly"] is True
    assert cookie["secure"] is True
    assert cookie["path"] == (
        f"/api/v1/event-checkin-stations/{first['public_token']}/"
    )
    assert int(cookie["max-age"]) > 0

    rotate_station(event, staff)
    stale = station.get(
        station_url("event-check-in-station-roster", first["public_token"]),
        **STATION_HEADERS,
    )
    assert stale.status_code == 403


def test_rotation_is_rechecked_inside_the_attendance_transaction():
    space = make_space()
    enable_offline(space)
    event = make_event(space)
    registration = register(event, make_member(space))
    staff = make_staff(space)
    first = rotate_station(event, staff)
    session_id = uuid4()
    roster = issue_roster(
        event,
        actor=None,
        kind="station",
        session_id=session_id,
        station_version=first["version"],
    )
    rotate_station(event, staff)

    with pytest.raises(PermissionDenied):
        synchronize(
            event,
            [{
                "operation_id": uuid4(),
                "checkin_token": str(registration.checkin_token),
                "reported_occurred_at": timezone.now(),
            }],
            lease=read_lease(roster["lease_token"]),
            actor=None,
            source=EventCheckInEvent.Source.VENUE_STATION,
            session_id=session_id,
            station_version=first["version"],
        )
    assert not EventCheckInEvent.objects.filter(registration=registration).exists()


def test_uniform_public_failure_does_not_enumerate_station_state():
    space = make_space()
    enable_offline(space)
    staff = make_staff(space)
    open_event = make_event(space)
    disabled_event = make_event(space, title="Disabled")
    closed_event = make_event(
        space,
        title="Future",
        starts_at=timezone.now() + timedelta(days=4),
    )
    valid = rotate_station(open_event, staff)
    disabled = rotate_station(disabled_event, staff)
    closed = rotate_station(closed_event, staff)
    client_for(staff).delete(
        reverse("admin-event-check-in-station", kwargs={"pk": disabled_event.pk})
    )

    attempts = [
        (valid["public_token"], "00000000"),
        (disabled["public_token"], disabled["pin"]),
        (closed["public_token"], closed["pin"]),
        (uuid4(), "00000000"),
    ]
    responses = []
    for token, pin in attempts:
        responses.append(
            APIClient().post(
                station_url("event-check-in-station-session", token),
                {"pin": pin},
                format="json",
                **STATION_HEADERS,
            )
        )

    assert {response.status_code for response in responses} == {403}
    assert len({str(response.data) for response in responses}) == 1
    assert AuditLog.objects.filter(
        action="event.station_pin_failed", target_id=str(open_event.pk)
    ).exists()


def test_pin_exchange_requires_csrf_header_and_an_exact_allowed_origin():
    space = make_space()
    enable_offline(space)
    event = make_event(space)
    payload = rotate_station(event, make_staff(space))
    url = station_url("event-check-in-station-session", payload["public_token"])

    missing_header = APIClient().post(
        url, {"pin": payload["pin"]}, format="json", HTTP_ORIGIN=ORIGIN
    )
    wrong_origin = APIClient().post(
        url,
        {"pin": payload["pin"]},
        format="json",
        HTTP_ORIGIN="https://localhost.attacker.example",
        HTTP_X_STATION_CSRF="present",
    )

    assert missing_header.status_code == wrong_origin.status_code == 403
    assert missing_header.data == wrong_origin.data


def test_anonymous_station_roster_and_sync_create_no_user():
    space = make_space()
    enable_offline(space)
    event = make_event(space)
    registration = register(event, make_member(space))
    payload = rotate_station(event, make_staff(space))
    user_count = User.objects.count()
    station, response = start_station(payload)
    assert response.status_code == 204

    roster = station.get(
        station_url("event-check-in-station-roster", payload["public_token"]),
        **STATION_HEADERS,
    )
    assert roster.status_code == 200
    sync = station.post(
        station_url("event-check-in-station-sync", payload["public_token"]),
        {
            "lease_token": roster.data["lease_token"],
            "operations": [{
                "operation_id": str(uuid4()),
                "checkin_token": str(registration.checkin_token),
                "reported_occurred_at": timezone.now().isoformat(),
            }],
        },
        format="json",
        **STATION_HEADERS,
    )

    assert sync.status_code == 200
    assert sync.data["results"][0]["outcome"] == "applied"
    history = EventCheckInEvent.objects.get(registration=registration)
    assert history.source == EventCheckInEvent.Source.VENUE_STATION
    assert history.actor_id is None
    assert history.station_version == payload["version"]
    assert User.objects.count() == user_count
