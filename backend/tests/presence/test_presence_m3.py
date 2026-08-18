from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.makerspaces import membership_services
from apps.makerspaces.models import Makerspace, MakerspaceMembership, MakerspaceRole
from apps.presence import services
from apps.presence.models import PresenceSession
from apps.presence.throttles import PresenceStartThrottle


def member(space, username="member"):
    user = User.objects.create_user(username=username, email=f"{username}@example.test", password="password")
    role = MakerspaceRole.objects.get(makerspace=space, slug="member")
    return user, MakerspaceMembership.objects.create(
        makerspace=space, user=user, assigned_role=role, role="custom", status="active"
    )


@pytest.mark.django_db(transaction=True)
def test_start_is_idempotent_then_supersedes_and_expiry_is_derived():
    space = Makerspace.objects.create(name="Presence", slug="presence")
    user, _ = member(space)
    first = services.start_session(user, space, 60)
    assert services.start_session(user, space, 60).pk == first.pk
    first.expires_at = timezone.now() + timedelta(minutes=5)
    first.save(update_fields=["expires_at"])
    replacement = services.start_session(user, space, 60)
    first.refresh_from_db()
    assert first.end_reason == PresenceSession.EndReason.SUPERSEDED
    assert replacement.pk != first.pk
    replacement.started_at = timezone.now() - timedelta(hours=2)
    replacement.expires_at = timezone.now() - timedelta(seconds=1)
    replacement.save(update_fields=["started_at", "expires_at"])
    assert services.current_session(user, space) is None


@pytest.mark.django_db(transaction=True)
def test_presets_validate_and_revoke_ends_active_session():
    space = Makerspace.objects.create(name="Preset", slug="preset", presence_preset_minutes=[30, 90])
    user, membership = member(space)
    with pytest.raises(ValidationError):
        services.start_session(user, space, 60)
    session = services.start_session(user, space, 30)
    actor = User.objects.create_user(username="root", email="root@example.test", password="password", is_superuser=True)
    membership_services.revoke_membership(actor, membership)
    session.refresh_from_db()
    assert session.end_reason == PresenceSession.EndReason.MEMBERSHIP_REVOKED


@pytest.mark.django_db
def test_presence_api_and_roster_minimize_pii():
    space = Makerspace.objects.create(name="Roster", slug="roster")
    user, membership = member(space)
    client = APIClient(); client.force_authenticate(user)
    started = client.post(f"/api/v1/public/{space.slug}/presence-sessions", {"duration_minutes": 60}, format="json")
    assert started.status_code == 201
    current = client.get(f"/api/v1/public/{space.slug}/presence-sessions/current")
    assert current.data["active"] is True and user.email not in str(current.data)
    manager = User.objects.create_user(username="manager", email="manager@example.test", password="password")
    manager_role = MakerspaceRole.objects.get(makerspace=space, slug="space_manager")
    MakerspaceMembership.objects.create(makerspace=space, user=manager, assigned_role=manager_role, role="space_manager")
    staff = APIClient(); staff.force_authenticate(manager)
    roster = staff.get(f"/api/v1/admin/makerspace/{space.id}/presence-sessions/current")
    assert roster.status_code == 200 and user.email not in str(roster.data)


@pytest.mark.django_db
def test_presence_start_throttles_replacements_but_not_idempotent_replays(
    monkeypatch,
):
    space = Makerspace.objects.create(name="Throttle", slug="presence-throttle")
    user, _ = member(space, "throttled-member")
    client = APIClient()
    client.force_authenticate(user)
    monkeypatch.setattr(
        PresenceStartThrottle,
        "THROTTLE_RATES",
        {**PresenceStartThrottle.THROTTLE_RATES, "presence_start": "2/hour"},
    )
    url = f"/api/v1/public/{space.slug}/presence-sessions"

    assert (
        client.post(url, {"duration_minutes": 60}, format="json").status_code
        == 201
    )
    for _ in range(3):
        # Exact replays return the existing row and do not consume the create budget.
        assert (
            client.post(url, {"duration_minutes": 60}, format="json").status_code
            == 201
        )
    assert (
        client.post(url, {"duration_minutes": 120}, format="json").status_code
        == 201
    )

    blocked = client.post(url, {"duration_minutes": 60}, format="json")

    assert blocked.status_code == 429
    assert PresenceSession.objects.filter(member=user, makerspace=space).count() == 2
