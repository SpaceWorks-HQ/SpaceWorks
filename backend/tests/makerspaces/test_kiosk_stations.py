"""Phase 9b kiosk Station admin lifecycle, PIN session and operator lease."""

from datetime import timedelta
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet
from django.core.cache import cache
from django.core.checks import run_checks
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.audit.models import AuditLog
from apps.makerspaces.kiosk_station_services import COOKIE_NAME, COOKIE_SALT
from apps.makerspaces.models import (
    MakerspaceMembership,
    Station,
    StationOperatorLease,
    StationSessionRevocation,
)
from apps.makerspaces.station_lease_cleanup import purge_expired_operator_leases
from apps.makerspaces.station_operator_leases import LEASE_SALT
from apps.organizations.models import (
    Organization,
    OrganizationMakerspace,
    OrganizationMembership,
)
from tests.events.checkin_helpers import client_for, make_member, make_space, make_staff
from tests.tenant_migration.source_gate_helpers import close_gate, make_actor

pytestmark = pytest.mark.django_db
ORIGIN = "http://localhost:5000"
HEADERS = {"HTTP_ORIGIN": ORIGIN, "HTTP_X_STATION_CSRF": "1"}


@pytest.fixture(autouse=True)
def kiosk_settings(settings):
    settings.API_CLIENT_ENC_KEY = Fernet.generate_key().decode("ascii")
    settings.EVENT_STATION_PIN_PEPPER = "test-only-independent-station-pepper"
    settings.CORS_ALLOWED_ORIGINS = [ORIGIN]
    cache.clear()
    yield
    cache.clear()


def kiosk_space(slug="kiosk-space"):
    space = make_space(slug)
    space.enabled_features = [*space.enabled_features, "inventory.kiosk"]
    space.save(update_fields=["enabled_features"])
    return space


def create(staff, space, kind="handover", name="Front desk"):
    url = reverse("admin-kiosk-station-list-create", kwargs={"makerspace_id": space.pk})
    return client_for(staff).post(url, {"name": name, "kind": kind}, format="json")


def start(payload, client=None, pin=None, **extra):
    client = client or APIClient()
    url = reverse("kiosk-station-session", kwargs={"public_token": payload["public_token"]})
    body = {"pin": pin or payload["pin"], **extra}
    return client, client.post(url, body, format="json", **HEADERS)


def lease_url(payload):
    return reverse(
        "kiosk-station-operator-lease", kwargs={"public_token": payload["public_token"]}
    )


def test_route_cookie_throttle_and_setting_contract(settings):
    token = uuid4()
    assert reverse("admin-kiosk-station-list-create", kwargs={"makerspace_id": 3}) == (
        "/api/v1/admin/makerspace/3/kiosk-stations/"
    )
    assert reverse("admin-kiosk-station-reveal", kwargs={"pk": 4}) == (
        "/api/v1/admin/kiosk-stations/4/reveal/"
    )
    assert reverse("kiosk-station-session", kwargs={"public_token": token}) == (
        f"/api/v1/kiosk-stations/{token}/session/"
    )
    assert COOKIE_NAME == "sw_kiosk_station"
    assert COOKIE_SALT == "spaceworks.kiosk.station-cookie.v1"
    assert LEASE_SALT == "spaceworks.kiosk.operator-lease.v1"
    rates = settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]
    assert rates["kiosk_station_pin_token"] == "10/hour"
    assert rates["kiosk_station_pin_ip"] == "30/hour"
    assert rates["kiosk_station_session"] == "120/hour"
    assert rates["kiosk_operator_lease"] == "30/hour"
    assert rates["kiosk_station_reveal"] == "5/hour"
    assert settings.KIOSK_STATION_SESSION_TTL_SECONDS == 12 * 3600
    assert settings.KIOSK_OPERATOR_LEASE_TTL_SECONDS == 8 * 3600
    assert settings.KIOSK_OPERATOR_LEASE_RETENTION_SECONDS == 7 * 86400
    assert "x-kiosk-operator-lease" in settings.CORS_ALLOW_HEADERS


def test_timing_checks_refuse_non_positive_and_lease_longer_than_session(settings):
    settings.KIOSK_OPERATOR_LEASE_TTL_SECONDS = 0
    assert "makerspaces.E102" in {e.id for e in run_checks()}
    settings.KIOSK_OPERATOR_LEASE_TTL_SECONDS = settings.KIOSK_STATION_SESSION_TTL_SECONDS + 1
    assert "makerspaces.E104" in {e.id for e in run_checks()}


def test_feature_off_refuses_admin_and_session():
    space = make_space("kiosk-off")
    staff = make_staff(space)
    assert create(staff, space).status_code == 400
    on = kiosk_space("kiosk-was-on")
    payload = create(make_staff(on), on).data
    on.enabled_features = [k for k in on.enabled_features if k != "inventory.kiosk"]
    on.save(update_fields=["enabled_features"])
    assert start(payload)[1].status_code == 403


def test_create_rotate_reveal_are_no_store_audited_and_kind_bounded():
    space = kiosk_space()
    staff = make_staff(space)
    staff.set_password("correct horse")
    staff.save()
    response = create(staff, space)
    assert response.status_code == 201
    assert response["Cache-Control"] == "private, no-store"
    assert response["Pragma"] == "no-cache"
    assert len(response.data["pin"]) == 8
    assert response.data["station_url"].endswith(f"/m/{space.slug}/kiosk/{response.data['public_token']}")
    assert create(staff, space, kind="event_checkin", name="x").status_code == 400
    station_id = response.data["id"]
    log = AuditLog.objects.get(action="kiosk.station_created")
    assert log.actor == staff and log.meta["station_id"] == station_id

    rotated = client_for(staff).post(
        reverse("admin-kiosk-station-rotate", kwargs={"pk": station_id}), format="json"
    )
    assert rotated.status_code == 200 and rotated["Pragma"] == "no-cache"
    assert rotated.data["version"] == 2 and rotated.data["pin"] != response.data["pin"]
    reveal_url = reverse("admin-kiosk-station-reveal", kwargs={"pk": station_id})
    client = client_for(staff)
    wrong = client.post(reveal_url, {"current_password": "nope"}, format="json")
    assert wrong.status_code == 403
    ok = client.post(reveal_url, {"current_password": "correct horse"}, format="json")
    assert ok.status_code == 200 and ok["Cache-Control"] == "private, no-store"
    assert ok.data["pin"] == rotated.data["pin"]
    statuses = [
        client.post(reveal_url, {"current_password": "correct horse"}, format="json").status_code
        for _ in range(4)
    ]
    assert statuses == [200, 200, 200, 429]


def test_cross_tenant_admin_is_refused_and_event_stations_are_not_kiosk_stations():
    space, other = kiosk_space("kiosk-a"), kiosk_space("kiosk-b")
    payload = create(make_staff(space), space).data
    outsider = make_staff(other, username="outsider")
    detail = reverse("admin-kiosk-station-detail", kwargs={"pk": payload["id"]})
    assert client_for(outsider).get(detail).status_code in (403, 404)
    assert create(outsider, space).status_code in (403, 404)
    event_station = Station.objects.create(makerspace=space, kind="event_checkin", name="e")
    staff = MakerspaceMembership.objects.filter(makerspace=space).first().user
    event_detail = reverse("admin-kiosk-station-detail", kwargs={"pk": event_station.pk})
    assert client_for(staff).get(event_detail).status_code == 404


def test_session_pin_origin_slug_bootstrap_and_failure_audit():
    space = kiosk_space()
    payload = create(make_staff(space), space).data
    _client, bad = start(payload, pin="00000000" if payload["pin"] != "00000000" else "11111111")
    assert bad.status_code == 403
    failed = AuditLog.objects.get(action="kiosk.station_pin_failed")
    assert failed.actor is None and failed.meta["station_id"] == payload["id"]
    url = reverse("kiosk-station-session", kwargs={"public_token": payload["public_token"]})
    no_csrf = APIClient().post(url, {"pin": payload["pin"]}, format="json", HTTP_ORIGIN=ORIGIN)
    assert no_csrf.status_code == 403
    evil = APIClient().post(
        url, {"pin": payload["pin"]}, format="json",
        HTTP_ORIGIN="https://evil.example", HTTP_X_STATION_CSRF="1",
    )
    assert evil.status_code == 403
    assert start(payload, makerspace_slug="another-space")[1].status_code == 403

    client, ok = start(payload, makerspace_slug=space.slug)
    assert ok.status_code == 201
    assert ok["Cache-Control"] == "private, no-store"
    assert set(ok.data) == {"station", "makerspace", "session_expires_at", "permitted_operations"}
    assert ok.data["makerspace"]["slug"] == space.slug
    assert "resolve_qr" in ok.data["permitted_operations"]
    cookie = ok.cookies[COOKIE_NAME]
    assert cookie["httponly"] and cookie["path"] == f"/api/v1/kiosk-stations/{payload['public_token']}/"
    started = AuditLog.objects.get(action="kiosk.station_session_started")
    assert started.actor is None and "station_session_id" in started.meta


def test_closed_source_gate_refuses_a_new_session():
    space = kiosk_space()
    payload = create(make_staff(space), space).data
    close_gate(space, make_actor())
    assert start(payload)[1].status_code != 201
    assert not AuditLog.objects.filter(action="kiosk.station_session_started").exists()


def test_lease_requires_login_cookie_and_binds_intersection_within_session():
    space = kiosk_space()
    staff = make_staff(space)
    payload = create(staff, space).data
    client, ok = start(payload)
    assert client.post(lease_url(payload), **HEADERS).status_code in (401, 403)
    client.force_authenticate(staff)
    issued = client.post(lease_url(payload), **HEADERS)
    assert issued.status_code == 201 and issued["Cache-Control"] == "private, no-store"
    assert "issue_request" in issued.data["allowed_actions"]
    assert "accept_request" not in issued.data["allowed_actions"]
    lease = StationOperatorLease.objects.get()
    assert lease.actor == staff and lease.station_version == 1
    assert lease.expires_at <= timezone.now() + timedelta(hours=8, seconds=5)
    log = AuditLog.objects.get(action="kiosk.operator_lease_issued")
    assert log.actor == staff and log.meta["operator_lease_id"] == str(lease.pk)

    no_cookie = APIClient()
    no_cookie.force_authenticate(staff)
    assert no_cookie.post(lease_url(payload), **HEADERS).status_code == 403
    member_client, _ = start(payload)
    member_client.force_authenticate(make_member(space))
    assert member_client.post(lease_url(payload), **HEADERS).status_code == 403


def test_scanner_station_lease_is_view_only():
    space = kiosk_space()
    staff = make_staff(space)
    payload = create(staff, space, kind="scanner", name="Scanner").data
    client, ok = start(payload)
    assert ok.data["permitted_operations"] == ["resolve_qr"]
    client.force_authenticate(staff)
    assert client.post(lease_url(payload), **HEADERS).data["allowed_actions"] == ["view_inventory"]


def test_organization_grant_is_an_authority_source_and_inactive_local_is_not():
    space = kiosk_space()
    payload = create(make_staff(space), space).data
    organization = Organization.objects.create(name="Org", slug="kiosk-org")
    OrganizationMakerspace.objects.create(
        organization=organization, makerspace=space,
        relationship=OrganizationMakerspace.Relationship.OWNER,
    )
    org_user = make_staff(make_space("unrelated"), username="org-user")
    OrganizationMembership.objects.create(
        organization=organization, user=org_user, granted_actions=["view_inventory"],
    )
    client, _ = start(payload)
    client.force_authenticate(org_user)
    granted = client.post(lease_url(payload), **HEADERS)
    assert granted.status_code == 201 and granted.data["allowed_actions"] == ["view_inventory"]

    inactive = make_staff(space, username="inactive")
    MakerspaceMembership.objects.filter(user=inactive, makerspace=space).update(status="revoked")
    client2, _ = start(payload)
    client2.force_authenticate(inactive)
    assert client2.post(lease_url(payload), **HEADERS).status_code == 403


def test_session_delete_records_revocation_and_revokes_leases():
    space = kiosk_space()
    staff = make_staff(space)
    payload = create(staff, space).data
    client, _ = start(payload)
    copied = client.cookies[COOKIE_NAME].value
    client.force_authenticate(staff)
    assert client.post(lease_url(payload), **HEADERS).status_code == 201
    url = reverse("kiosk-station-session", kwargs={"public_token": payload["public_token"]})
    assert client.delete(url, **HEADERS).status_code == 204
    assert StationSessionRevocation.objects.count() == 1
    assert StationOperatorLease.objects.get().revoked_at is not None
    replay = APIClient()
    replay.cookies[COOKIE_NAME] = copied
    replay.force_authenticate(staff)
    assert replay.post(lease_url(payload), **HEADERS).status_code == 403


def test_rotation_and_disable_invalidate_the_session_and_leases():
    space = kiosk_space()
    staff = make_staff(space)
    payload = create(staff, space).data
    client, _ = start(payload)
    client.force_authenticate(staff)
    assert client.post(lease_url(payload), **HEADERS).status_code == 201
    client_for(staff).post(reverse("admin-kiosk-station-rotate", kwargs={"pk": payload["id"]}))
    assert StationOperatorLease.objects.get().revoked_at is not None
    assert client.post(lease_url(payload), **HEADERS).status_code == 403
    detail = reverse("admin-kiosk-station-detail", kwargs={"pk": payload["id"]})
    disabled = client_for(staff).delete(detail)
    assert disabled.status_code == 200 and disabled.data["enabled"] is False
    assert AuditLog.objects.filter(action="kiosk.station_disabled", actor=staff).exists()


def test_cleanup_purges_only_past_retention_and_quarantine_revokes(settings):
    from apps.backup.recovery import enter_quarantine
    from tests.backup.test_recovery import recovery_fixture

    space = kiosk_space()
    staff = make_staff(space)
    payload = create(staff, space).data
    station = Station.objects.get(pk=payload["id"])
    now = timezone.now()
    old = StationOperatorLease.objects.create(
        makerspace=space, station=station, actor=staff, station_session_id=uuid4(),
        station_version=1, allowed_actions=["view_inventory"], issued_at=now,
        expires_at=now - timedelta(days=8),
    )
    live = StationOperatorLease.objects.create(
        makerspace=space, station=station, actor=staff, station_session_id=uuid4(),
        station_version=1, allowed_actions=["view_inventory"], issued_at=now,
        expires_at=now + timedelta(hours=1),
    )
    StationSessionRevocation.objects.create(
        session_id=uuid4(), station=station, expires_at=now - timedelta(minutes=1)
    )
    counts = purge_expired_operator_leases(now=now)
    assert counts["leases"] == 1 and counts["revocations"] == 1
    assert list(StationOperatorLease.objects.values_list("pk", flat=True)) == [live.pk]
    assert not StationOperatorLease.objects.filter(pk=old.pk).exists()

    _admin, _other, restore = recovery_fixture()
    enter_quarantine(restore, "disaster restore")
    live.refresh_from_db()
    assert live.revoked_at is not None
