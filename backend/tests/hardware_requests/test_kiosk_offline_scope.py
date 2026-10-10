"""Lease scope metadata is descriptive; the signed channel still owns authority."""

import pytest
from django.urls import reverse

from apps.audit.models import AuditLog
from apps.makerspaces.models_station_leases import StationOperatorLease
from tests.events.checkin_helpers import make_staff
from tests.hardware_requests.test_kiosk_online import (
    kiosk_settings,  # noqa: F401 — reuse independent encryption/origin fixture
    kiosk_space,
    leased,
)

pytestmark = pytest.mark.django_db


def test_operator_lease_exposes_exact_human_and_session_scope_no_store():
    space = kiosk_space()
    staff = make_staff(space)
    client, token, headers, station = leased(space, staff)
    response = client.post(
        reverse("kiosk-station-operator-lease", kwargs={"public_token": token}),
        **headers,
    )
    assert response.status_code == 201, response.data
    lease = StationOperatorLease.objects.get(pk=response.data["lease_id"])
    assert response.data["session_id"] == str(lease.station_session_id)
    assert response.data["actor_id"] == staff.pk == lease.actor_id
    assert lease.station_id == station["id"]
    assert lease.makerspace_id == space.pk
    assert response["Cache-Control"] == "private, no-store"
    log = AuditLog.objects.filter(action="kiosk.operator_lease_issued").latest("created_at")
    assert log.actor == staff
    assert log.meta["station_session_id"] == response.data["session_id"]
