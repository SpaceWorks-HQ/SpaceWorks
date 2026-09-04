from datetime import datetime, timedelta
from uuid import UUID, uuid4
import hashlib
import hmac

import pytest
from cryptography.fernet import Fernet
from django.contrib.auth.hashers import check_password
from django.core.cache import cache
from django.core import signing
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from django.urls import reverse
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.events.checkin_tokens import STATION_COOKIE_SALT, read_lease
from apps.events.models import EventCheckInEvent, EventStationBinding
from apps.makerspaces.models import Station, StationCredential
from apps.events.services_checkin_roster import issue_roster
from apps.events.services_checkin_sync import synchronize
from apps.events.services_station import (
    STATION_COOKIE_NAME,
    STATION_REFUSAL,
    credential_for_event,
)
from apps.makerspaces.station_credentials import PasswordStepUpUnavailable
from apps.events.throttles import (
    EventStationPinIpThrottle,
    EventStationPinTokenThrottle,
    EventStationRevealThrottle,
    EventStationSessionThrottle,
)
from tests.events.checkin_helpers import (
    client_for,
    make_event,
    make_member,
    make_space,
    make_staff,
    register,
)
from tests.tenant_migration.source_gate_helpers import close_gate, make_actor

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


def test_station_route_cookie_and_throttle_contract(settings):
    token = uuid4()
    assert reverse("admin-event-check-in-station", kwargs={"pk": 17}) == (
        "/api/v1/admin/events/17/check-in/station/"
    )
    assert reverse("admin-event-check-in-station-rotate", kwargs={"pk": 17}) == (
        "/api/v1/admin/events/17/check-in/station/rotate/"
    )
    assert reverse("admin-event-check-in-station-reveal", kwargs={"pk": 17}) == (
        "/api/v1/admin/events/17/check-in/station/reveal/"
    )
    assert station_url("event-check-in-station-session", token) == (
        f"/api/v1/event-checkin-stations/{token}/session/"
    )
    assert station_url("event-check-in-station-roster", token) == (
        f"/api/v1/event-checkin-stations/{token}/roster/"
    )
    assert station_url("event-check-in-station-sync", token) == (
        f"/api/v1/event-checkin-stations/{token}/sync/"
    )
    assert STATION_COOKIE_NAME == "sw_event_station"
    assert STATION_COOKIE_SALT == "spaceworks.events.station-cookie.v1"
    assert EventStationPinTokenThrottle.scope == "event_station_pin_token"
    assert EventStationPinIpThrottle.scope == "event_station_pin_ip"
    assert EventStationSessionThrottle.scope == "event_station_session"
    assert EventStationRevealThrottle.scope == "event_station_reveal"
    rates = settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]
    assert rates["event_station_pin_token"] == "10/hour"
    assert rates["event_station_pin_ip"] == "30/hour"
    assert rates["event_station_session"] == "120/hour"
    assert rates["event_station_reveal"] == "5/hour"


def test_station_status_and_pin_material_contract(settings):
    space = make_space()
    enable_offline(space)
    event = make_event(space)
    staff = make_staff(space)
    client = client_for(staff)
    status_url = reverse("admin-event-check-in-station", kwargs={"pk": event.pk})

    empty = client.get(status_url)
    assert empty.status_code == 200
    assert empty.data == {"configured": False}
    assert empty["Cache-Control"] == "private, no-store"

    payload = rotate_station(event, staff)
    credential = StationCredential.objects.get(station__event_binding__event=event)
    message = (
        f"spaceworks:event-station-pin:v1:{event.pk}:{credential.version}:"
        f"{payload['pin']}"
    ).encode()
    expected_material = hmac.new(
        settings.EVENT_STATION_PIN_PEPPER.encode(), message, hashlib.sha256
    ).hexdigest()
    assert check_password(expected_material, credential.pin_digest)

    configured = client.get(status_url)
    assert configured.status_code == 200
    assert set(configured.data) == {
        "configured", "enabled", "public_token", "version", "station_url",
        "rotated_at",
    }
    assert configured.data["configured"] is True
    assert configured.data["enabled"] is True
    assert configured.data["public_token"] == str(credential.public_token)
    assert configured.data["version"] == 1


def test_station_cookie_payload_contract():
    space = make_space()
    enable_offline(space)
    event = make_event(space)
    payload = rotate_station(event, make_staff(space))
    _client, response = start_station(payload)

    assert response.status_code == 204
    cookie = response.cookies[STATION_COOKIE_NAME]
    decoded = signing.loads(cookie.value, salt=STATION_COOKIE_SALT)
    assert set(decoded) == {"public_token", "version", "session_id", "expires_at"}
    assert decoded["public_token"] == str(payload["public_token"])
    assert decoded["version"] == payload["version"]
    assert str(UUID(decoded["session_id"])) == decoded["session_id"]
    assert timezone.now() < datetime.fromisoformat(decoded["expires_at"])


def test_shared_station_and_event_binding_constraints():
    first = make_space("station-constraints-first")
    second = make_space("station-constraints-second")
    event = make_event(first)
    station = Station.objects.create(
        makerspace=first,
        kind=Station.Kind.EVENT_CHECKIN,
        name="Front door",
    )
    EventStationBinding.objects.create(event=event, station=station)
    StationCredential.objects.create(
        station=station,
        pin_digest="digest",
        pin_ciphertext=b"ciphertext",
    )

    with pytest.raises(IntegrityError), transaction.atomic():
        Station.objects.create(
            makerspace=first,
            kind=Station.Kind.EVENT_CHECKIN,
            name="Front door",
        )
    assert Station.objects.create(
        makerspace=second,
        kind=Station.Kind.EVENT_CHECKIN,
        name="Front door",
    )
    with pytest.raises(IntegrityError), transaction.atomic():
        StationCredential.objects.create(
            station=station,
            pin_digest="second digest",
            pin_ciphertext=b"second ciphertext",
        )
    with pytest.raises(DjangoValidationError):
        EventStationBinding.objects.create(
            event=make_event(first, title="Reused station"),
            station=station,
        )
    with pytest.raises(DjangoValidationError):
        EventStationBinding.objects.create(
            event=make_event(second, title="Cross tenant"),
            station=station,
        )
    wrong_kind = Station.objects.create(
        makerspace=first,
        kind=Station.Kind.SCANNER,
        name="Scanner",
    )
    with pytest.raises(DjangoValidationError):
        EventStationBinding.objects.create(
            event=make_event(first, title="Wrong kind"),
            station=wrong_kind,
        )
    with pytest.raises(DjangoValidationError):
        EventStationBinding.objects.create(
            event=event,
            station=Station.objects.create(
                makerspace=first,
                kind=Station.Kind.EVENT_CHECKIN,
                name="Second station",
            ),
        )
    Station.objects.filter(pk=station.pk).update(kind=Station.Kind.SCANNER)
    station.refresh_from_db()
    with pytest.raises(DjangoValidationError):
        credential_for_event(event)


def test_station_controls_are_feature_gated_on_both_sides():
    space = make_space()
    event = make_event(space)
    staff = make_staff(space)

    assert client_for(staff).post(rotate_url(event), {}, format="json").status_code == 400
    assert not StationCredential.objects.exists()

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
    credential = StationCredential.objects.get(station__event_binding__event=event)
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
    assert list(
        AuditLog.objects.filter(action="event.station_pin_rotated")
        .order_by("created_at")
        .values_list("meta", flat=True)
    ) == [
        {"event_id": event.pk, "station_version": 1},
        {"event_id": event.pk, "station_version": 2},
    ]
    reveal_log = AuditLog.objects.get(action="event.station_pin_revealed")
    assert reveal_log.actor_id == staff.pk
    assert reveal_log.meta == {"event_id": event.pk, "station_version": 1}


def test_reveal_preserves_step_up_error_codes():
    space = make_space("station-reveal-errors")
    enable_offline(space)
    event = make_event(space)
    staff = make_staff(space)
    rotate_station(event, staff)
    url = reverse("admin-event-check-in-station-reveal", kwargs={"pk": event.pk})

    unavailable = client_for(staff).post(
        url, {"current_password": "anything"}, format="json"
    )
    assert unavailable.status_code == 409
    assert PasswordStepUpUnavailable.default_code == "password_step_up_unavailable"
    assert unavailable.data["detail"] == PasswordStepUpUnavailable.default_detail

    staff.set_password("correct password")
    staff.save(update_fields=["password"])
    incorrect = client_for(staff).post(
        url, {"current_password": "wrong password"}, format="json"
    )
    assert incorrect.status_code == 403
    assert incorrect.data["detail"].code == "permission_denied"


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


def test_disable_refuses_sessions_and_rotation_reenables_the_same_station():
    space = make_space("station-disable")
    enable_offline(space)
    event = make_event(space)
    staff = make_staff(space)
    first = rotate_station(event, staff)
    client = client_for(staff)

    disabled = client.delete(
        reverse("admin-event-check-in-station", kwargs={"pk": event.pk})
    )
    assert disabled.status_code == 200
    assert disabled.data["configured"] is True
    assert disabled.data["enabled"] is False
    assert disabled.data["version"] == 1
    _station, refused = start_station(first)
    assert refused.status_code == 403

    second = rotate_station(event, staff)
    assert second["public_token"] == first["public_token"]
    assert second["version"] == 2
    _station, accepted = start_station(second)
    assert accepted.status_code == 204
    assert AuditLog.objects.get(action="event.station_disabled").meta == {
        "event_id": event.pk,
        "station_version": 1,
    }
    session_log = AuditLog.objects.get(action="event.station_session_started")
    assert session_log.actor_id is None
    assert set(session_log.meta) == {"event_id", "session_id", "station_version"}
    assert session_log.meta["event_id"] == event.pk
    assert session_log.meta["station_version"] == 2


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
    assert {response.data["detail"] for response in responses} == {STATION_REFUSAL}
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
    assert missing_header.data["detail"] == STATION_REFUSAL


def test_closed_source_gate_refuses_new_station_sessions():
    space = make_space("station-source-gate")
    enable_offline(space)
    event = make_event(space)
    payload = rotate_station(event, make_staff(space))
    close_gate(space, make_actor("station-source-gate-owner"))

    _client, response = start_station(payload)

    assert response.status_code == 423
    assert response.json()["code"] == "tenant_migration_quiesced"


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
    assert sync["Cache-Control"] == "private, no-store"
    assert sync.data["results"][0]["outcome"] == "applied"
    history = EventCheckInEvent.objects.get(registration=registration)
    assert history.source == EventCheckInEvent.Source.VENUE_STATION
    assert history.actor_id is None
    assert history.station_version == payload["version"]
    assert User.objects.count() == user_count
