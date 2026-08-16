import pytest
from django.urls import reverse

from apps.accounts.models import User
from apps.makerspaces.models import MakerspaceMembership
from tests.return_helpers import authenticated_client, make_member, make_space, make_user

pytestmark = pytest.mark.django_db


def make_superadmin(username):
    return make_user(
        username,
        role=User.Role.SUPERADMIN,
        access_status=User.AccessStatus.ACTIVE,
    )


def reset_password_url(user):
    return reverse("admin-user-reset-password", kwargs={"pk": user.id})


def test_makerspace_admin_resets_managed_staff():
    space = make_space("admin-reset-managed")
    admin = make_member("admin-reset-manager", space)
    target = make_member(
        "admin-reset-inventory",
        space,
        membership_role=MakerspaceMembership.Role.INVENTORY_MANAGER,
        role=User.Role.REQUESTER,
    )
    client = authenticated_client(admin)

    first = client.post(reset_password_url(target), {}, format="json")
    target.refresh_from_db()
    second = client.post(reset_password_url(target), {}, format="json")
    target.refresh_from_db()

    assert first.status_code == 200
    assert first.data["temporary_password"]
    assert target.must_change_password is True
    assert second.status_code == 200
    assert second.data["temporary_password"]


def test_cannot_reset_superadmin_target():
    space = make_space("admin-reset-super-target")
    actor = make_member("admin-reset-super-actor", space)
    target = make_superadmin("admin-reset-super-target")

    response = authenticated_client(actor).post(reset_password_url(target), {}, format="json")

    # 404-before-403: a superadmin target is outside a makerspace admin's scope, so it
    # is "not found" rather than "forbidden" — no probing for user existence by id.
    assert response.status_code == 404


def test_superadmin_break_glass_resets_hidden_only_space_manager():
    # Hard-hide break-glass: a superadmin MAY reset a Space Manager who manages
    # ONLY hard-hidden makerspace(s) — the recovery path when the space is locked
    # out and the instance has no SMTP for self-service forgot-password.
    hidden_space = make_space("admin-reset-hidden")
    hidden_space.superadmin_access_enabled = False
    hidden_space.save(update_fields=["superadmin_access_enabled"])
    target = make_member("admin-reset-hidden-manager", hidden_space)
    superadmin = make_superadmin("admin-reset-hidden-super")

    response = authenticated_client(superadmin).post(
        reset_password_url(target),
        {},
        format="json",
    )

    assert response.status_code == 200
    assert response.data["temporary_password"]
    target.refresh_from_db()
    assert target.must_change_password is True


def test_superadmin_break_glass_blocked_when_also_enabled_space_manager():
    # If the target also manages a superadmin-access-ENABLED space, break-glass is
    # refused — it must not become a way to take over an enabled-space Space Manager.
    hidden_space = make_space("admin-reset-mixed-hidden")
    hidden_space.superadmin_access_enabled = False
    hidden_space.save(update_fields=["superadmin_access_enabled"])
    enabled_space = make_space("admin-reset-mixed-enabled")
    target = make_member("admin-reset-mixed-manager", hidden_space)
    MakerspaceMembership.objects.create(
        user=target,
        makerspace=enabled_space,
        role=MakerspaceMembership.Role.SPACE_MANAGER,
    )
    superadmin = make_superadmin("admin-reset-mixed-super")

    response = authenticated_client(superadmin).post(
        reset_password_url(target),
        {},
        format="json",
    )

    assert response.status_code == 403


def test_superadmin_cannot_reset_hidden_non_space_manager():
    hidden_space = make_space("admin-reset-hidden-inventory")
    make_member("admin-reset-hidden-inventory-manager", hidden_space)
    hidden_space.superadmin_access_enabled = False
    hidden_space.save(update_fields=["superadmin_access_enabled"])
    target = make_member(
        "admin-reset-hidden-inventory-target",
        hidden_space,
        membership_role=MakerspaceMembership.Role.INVENTORY_MANAGER,
        role=User.Role.REQUESTER,
    )
    superadmin = make_superadmin("admin-reset-hidden-inventory-super")

    response = authenticated_client(superadmin).post(
        reset_password_url(target),
        {},
        format="json",
    )

    assert response.status_code == 403
    target.refresh_from_db()
    assert target.must_change_password is False


def test_non_superadmin_cannot_reset_peer_space_manager():
    space = make_space("admin-reset-peer")
    actor = make_member("admin-reset-peer-actor", space)
    target = make_member("admin-reset-peer-target", space)

    response = authenticated_client(actor).post(reset_password_url(target), {}, format="json")

    # Peer Space Manager in the SAME space: target is in scope (found), then blocked 403.
    assert response.status_code == 403


def test_non_superadmin_cannot_reset_user_outside_scope():
    space_a = make_space("admin-reset-scope-a")
    space_b = make_space("admin-reset-scope-b")
    actor = make_member("admin-reset-scope-actor", space_a)
    target = make_member(
        "admin-reset-scope-target",
        space_b,
        membership_role=MakerspaceMembership.Role.INVENTORY_MANAGER,
        role=User.Role.REQUESTER,
    )

    response = authenticated_client(actor).post(reset_password_url(target), {}, format="json")

    # Target lives only in space B, outside the actor's authority → 404, not a 403 that
    # would confirm the user id exists.
    assert response.status_code == 404


def test_admin_reset_blacklists_outstanding_tokens():
    from rest_framework_simplejwt.token_blacklist.models import (
        BlacklistedToken,
        OutstandingToken,
    )
    from apps.accounts.tokens import SpaceWorksRefreshToken

    space = make_space("admin-reset-revoke")
    admin = make_member("admin-reset-revoke-actor", space)
    target = make_member(
        "admin-reset-revoke-target",
        space,
        membership_role=MakerspaceMembership.Role.INVENTORY_MANAGER,
        role=User.Role.REQUESTER,
    )
    # A live session for the target: its refresh token is recorded as outstanding.
    SpaceWorksRefreshToken.for_user(target)
    outstanding = OutstandingToken.objects.filter(user=target)
    assert outstanding.exists()
    assert not BlacklistedToken.objects.filter(token__in=outstanding).exists()

    response = authenticated_client(admin).post(reset_password_url(target), {}, format="json")

    assert response.status_code == 200
    # Every pre-reset refresh token is now blacklisted, so the old session can't refresh.
    assert BlacklistedToken.objects.filter(token__in=outstanding).count() == outstanding.count()
