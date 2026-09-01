"""apps/presence under the tombstone profile (plan B5/B6, phase 12).

Presence is the odd one out twice over.

It owns **no module key**, like warranty, so `unavailable_apps` is what tells the
clients. And it is the only app whose removal changes behaviour rather than only
withdrawing a surface: seven member-facing flows call
`require_active_member_presence` as a bare precondition, so a hard session requirement
in a deployment with no check-in would refuse all seven forever. The guard therefore
skips the **session** check when presence is tombstoned and keeps enforcing membership
and the waiver -- and the tests below pin both halves of that, because a regression in
either direction is serious: leaving the session hard breaks the install, dropping
membership or the waiver removes a real control.
"""

import pytest
from django.contrib import admin
from django.urls import Resolver404, resolve
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.makerspaces.models import Makerspace, MakerspaceMembership, MakerspaceWaiver
from apps.makerspaces.platform import bootstrap_payload
from apps.presence.guard import (
    MemberPresenceRequired,
    WaiverAcceptanceRequired,
    require_active_member_presence,
)
from apps.presence.models import PresenceSession
from apps.separability.registry import runtime_active
from apps.separability.tombstones import unavailable_apps

pytestmark = pytest.mark.django_db


# --------------------------------------------------------------------------
# Surfaces: gone.
# --------------------------------------------------------------------------

def test_the_app_is_registered_as_inactive():
    assert runtime_active("presence") is False


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/public/forge/presence-sessions",
        "/api/v1/public/forge/presence-sessions/current",
        "/api/v1/public/forge/presence-sessions/current/end",
        "/api/v1/admin/makerspace/1/presence-sessions/current",
    ],
)
def test_no_presence_route_resolves(path):
    with pytest.raises(Resolver404):
        resolve(path)


def test_the_neighbouring_public_routes_still_resolve():
    """Presence shared /api/v1/public/ with events and bookings.

    Machines, not events or bookings: phases 13 and 14 make both of those separable and
    this profile tombstones them. A neighbour assertion is only worth anything while the
    neighbour is still there, so it has to name a route no later phase withdraws --
    `apps.machines` is the kernel and is not separable.
    """
    assert resolve("/api/v1/public/forge/machines").url_name == "public-machines"


def test_the_admin_does_not_register_the_model():
    assert PresenceSession not in admin.site._registry


def test_the_openapi_schema_does_not_advertise_presence():
    response = APIClient().get("/schema/?format=json")

    assert response.status_code == 200
    assert b"presence-sessions" not in response.content


def test_the_deployment_reports_presence_as_unavailable():
    assert "presence" in unavailable_apps()


def test_the_bootstrap_stops_asking_the_browser_for_coordinates():
    """`presence.geofence` is parentless, so no module key could express this."""
    space = _space("geofenced", geofence_enabled=True, geofence_latitude=1, geofence_longitude=2)
    space.enabled_features = sorted(set(space.enabled_features) | {"presence.geofence"})
    space.save(update_fields=["enabled_features"])

    assert "geofence_enabled" not in bootstrap_payload(space)["makerspace"]


# --------------------------------------------------------------------------
# The guard: the session lapses, membership and the waiver do not.
# --------------------------------------------------------------------------

def test_a_member_may_act_without_a_check_in_session():
    """Otherwise all seven dependent flows refuse forever -- a stuck install, not a small one."""
    space = _space("presence-off")
    member = _member("checked-out")
    MakerspaceMembership.objects.create(user=member, makerspace=space, status="active")

    result = require_active_member_presence(member, space)

    assert result.session is None
    assert result.membership.user_id == member.pk
    assert not PresenceSession.objects.exists()


def test_a_non_member_is_still_refused():
    space = _space("presence-off-stranger")
    stranger = _member("stranger")

    with pytest.raises(MemberPresenceRequired):
        require_active_member_presence(stranger, space)


def test_an_unaccepted_waiver_is_still_refused():
    space = _space("presence-off-waiver")
    member = _member("unwaived")
    MakerspaceMembership.objects.create(user=member, makerspace=space, status="active")
    MakerspaceWaiver.objects.create(makerspace=space, version=1, body="Be careful.", is_active=True)

    with pytest.raises(WaiverAcceptanceRequired):
        require_active_member_presence(member, space)


def test_a_restricted_user_is_still_refused():
    space = _space("presence-off-restricted")
    member = _member("restricted", access_status=User.AccessStatus.RESTRICTED)
    MakerspaceMembership.objects.create(user=member, makerspace=space, status="active")

    with pytest.raises(MemberPresenceRequired):
        require_active_member_presence(member, space)


# --------------------------------------------------------------------------
# Data: untouched.
# --------------------------------------------------------------------------

def test_existing_sessions_are_still_readable():
    from datetime import timedelta

    from django.utils import timezone

    space = _space("retained-presence")
    member = _member("retained-member")
    membership = MakerspaceMembership.objects.create(user=member, makerspace=space, status="active")
    now = timezone.now()
    session = PresenceSession.objects.create(
        makerspace=space,
        member=member,
        membership=membership,
        started_at=now,
        expires_at=now + timedelta(hours=1),
    )

    assert PresenceSession.objects.get(pk=session.pk).member_id == member.pk


def _space(slug, **extra):
    return Makerspace.objects.create(name=slug, slug=slug, **extra)


def _member(username, **extra):
    return User.objects.create_user(username=username, password="pw12345!", **extra)
