"""Phase 9 -- the identity seam, and what an accounts-off deployment can still do.

Two halves, and the second is the one that matters: switching `accounts` off must not
leave a makerspace unable to name the person standing at the counter. Every requester
relation in the system is a non-null PROTECT FK to `User`, so "account-less" can only
ever mean *self-service is gone*, never *identity is gone*.
"""

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.accounts import member_identity
from apps.makerspaces.models import Makerspace, MakerspaceMembership, MakerspaceRole
from apps.makerspaces.module_install import uninstall_module
from apps.makerspaces.walk_in_services import create_walk_in_member

pytestmark = pytest.mark.django_db

CONFIG_URL = "/api/v1/config"
PHONE_START_URL = "/api/v1/auth/phone/login/start"
PHONE_CONFIRM_URL = "/api/v1/auth/phone/login/confirm"
SIGNUP_URL = "/api/v1/auth/member-sign-up"
GOOGLE_URL = "/api/v1/auth/social/google"


def make_space(slug="identity-space"):
    return Makerspace.objects.create(name=slug, slug=slug)


def accounts_off(makerspace, actor=None):
    """Uninstall through the real service, so dependency and feature pruning run."""
    uninstall_module(makerspace, "mobile", actor=actor)
    uninstall_module(makerspace, "membership", actor=actor)
    uninstall_module(makerspace, "accounts", actor=actor)


def front_desk(makerspace, username="front-desk"):
    user = User.objects.create_user(
        username=f"{username}-{makerspace.slug}",
        email=f"{username}-{makerspace.slug}@example.test",
        access_status=User.AccessStatus.ACTIVE,
    )
    MakerspaceMembership.objects.create(
        user=user,
        makerspace=makerspace,
        role=MakerspaceMembership.Role.INVENTORY_MANAGER,
        assigned_role=MakerspaceRole.objects.get(
            makerspace=makerspace, slug="inventory_manager"
        ),
    )
    return user


def authed(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def walk_in_url(makerspace):
    return f"/api/v1/admin/makerspaces/{makerspace.id}/walk-in-members"


# --- the seam ---------------------------------------------------------------------


def test_a_configured_oidc_provider_is_never_gated():
    """The space's own directory is the alternative, so it cannot go with the default."""
    space = make_space()
    accounts_off(space)

    assert member_identity.member_accounts_enabled() is False
    assert member_identity.member_login_allowed("oidc:campus") is True
    assert member_identity.member_login_allowed("google") is False
    # A slug that merely contains the word cannot impersonate the namespace.
    assert member_identity.member_login_allowed("google-oidc") is False


def test_staff_surface_is_never_gated():
    space = make_space()
    accounts_off(space)

    assert member_identity.member_login_allowed("google", surface="staff") is True
    assert member_identity.member_login_allowed(None, surface="staff") is True


def test_a_broken_capability_read_fails_open(monkeypatch):
    """A broken check must never lock people out of signing in."""
    import apps.makerspaces.deployment_modules as deployment_modules

    def explode():
        raise RuntimeError("registry unavailable")

    monkeypatch.setattr(deployment_modules, "member_accounts_enabled", explode)
    assert member_identity.member_accounts_enabled() is True


# --- the gated surfaces -----------------------------------------------------------


def test_member_login_surfaces_close_and_config_says_so(monkeypatch):
    space = make_space()
    monkeypatch.setattr(
        "apps.integrations.sms.sms_configured", lambda: True, raising=False
    )
    client = APIClient()

    before = client.get(CONFIG_URL).data
    assert "member_accounts" not in before, "the payload must be unchanged while on"
    assert before.get("phone_login") == {"enabled": True}

    accounts_off(space)

    after = client.get(CONFIG_URL).data
    assert after["member_accounts"] == {"enabled": False}
    assert "phone_login" not in after
    assert client.post(PHONE_START_URL, {"phone": "+15550100200"}, format="json").status_code == 404
    assert client.post(
        PHONE_CONFIRM_URL, {"phone": "+15550100200", "code": "123456"}, format="json"
    ).status_code == 404


def test_member_surface_social_login_is_refused_but_staff_is_not():
    space = make_space()
    accounts_off(space)
    client = APIClient()

    payload = {
        "id_token": "irrelevant",
        "nonce": "irrelevant",
        "surface": "member",
        "delivery": "web",
        "client_platform": "web",
    }
    assert client.post(GOOGLE_URL, payload, format="json").status_code == 404
    # The staff surface gets past the gate and fails later, on the unconfigured
    # provider -- which is the point: the gate is not what stops it.
    staff = client.post(GOOGLE_URL, {**payload, "surface": "staff"}, format="json")
    assert staff.status_code in (401, 404, 503)


def test_self_sign_up_stays_generic_when_accounts_are_off():
    space = make_space()
    accounts_off(space)
    client = APIClient()

    response = client.post(
        SIGNUP_URL,
        {"display_name": "Nobody", "email": "nobody@example.test", "password": "Safe pass 947!"},
        format="json",
    )
    assert response.status_code == 200
    assert not User.objects.filter(email="nobody@example.test").exists()


# --- walk-in records --------------------------------------------------------------


def test_front_desk_can_name_a_walk_in_with_accounts_off():
    space = make_space()
    staff = front_desk(space)
    accounts_off(space, actor=staff)

    response = authed(staff).post(
        walk_in_url(space), {"display_name": "Ada Lovelace"}, format="json"
    )
    assert response.status_code == 201, response.data

    user = User.objects.get(pk=response.data["user_id"])
    assert user.display_name == "Ada Lovelace"
    assert user.has_usable_password() is False, "a walk-in record is not a login"
    assert user.email == ""
    assert MakerspaceMembership.objects.filter(
        makerspace=space, user=user, status="active"
    ).exists()


def test_a_typed_number_never_becomes_a_login_identity():
    space = make_space()
    staff = front_desk(space)

    membership = create_walk_in_member(
        staff, space, display_name="Grace Hopper", phone="+15550199888"
    )
    membership.user.refresh_from_db()
    assert membership.user.phone == "+15550199888"
    # phone_e164 is a login credential under a partial unique constraint. A number
    # typed at a counter has not been proven to belong to the person standing there.
    assert membership.user.phone_e164 == ""
    assert membership.user.phone_verified_at is None


def test_two_walk_ins_with_the_same_name_both_get_a_record():
    space = make_space()
    staff = front_desk(space)

    first = create_walk_in_member(staff, space, display_name="Alex")
    second = create_walk_in_member(staff, space, display_name="Alex")
    assert first.user_id != second.user_id
    assert first.user.username != second.user.username


def test_a_known_email_is_refused_and_never_binds_to_the_account():
    """The form names strangers. Attaching a real account is a membership decision.

    It sits behind `ISSUE_DIRECT_LOAN`, so binding here would let anyone who can hand
    out a tool add an existing account to the roster -- and silently reactivate a
    membership someone deliberately revoked.
    """
    from rest_framework.exceptions import ValidationError

    space = make_space()
    staff = front_desk(space)
    known = User.objects.create_user(
        username="known-member", email="known@example.test",
        access_status=User.AccessStatus.ACTIVE,
    )
    MakerspaceMembership.objects.create(
        user=known, makerspace=space, role=MakerspaceMembership.Role.CUSTOM,
        assigned_role=MakerspaceRole.objects.get(makerspace=space, slug="member"),
        status="revoked",
    )

    with pytest.raises(ValidationError):
        create_walk_in_member(staff, space, display_name="Known", email="known@example.test")
    assert MakerspaceMembership.objects.get(user=known, makerspace=space).status == "revoked"

    # Also refused for an account this makerspace has never seen.
    stranger = make_space("other-space")
    outside = User.objects.create_user(
        username="outside-member", email="outside@example.test",
        access_status=User.AccessStatus.ACTIVE,
    )
    with pytest.raises(ValidationError):
        create_walk_in_member(staff, space, display_name="Outside", email="outside@example.test")
    assert not MakerspaceMembership.objects.filter(user=outside).exists()
    assert not MakerspaceMembership.objects.filter(makerspace=stranger).exists()


def test_a_walk_in_can_be_a_direct_loan_borrower():
    """The whole point: identity survives so the downstream flows do too."""
    space = make_space()
    staff = front_desk(space)
    membership = create_walk_in_member(staff, space, display_name="Counter Person")

    listed = authed(staff).get(
        f"/api/v1/admin/makerspace/{space.id}/direct-loan-members"
    )
    assert listed.status_code == 200
    assert membership.user_id in [row["user_id"] for row in listed.data["results"]]


def test_walk_in_creation_needs_the_handout_action():
    space = make_space()
    outsider = User.objects.create_user(
        username="outsider", email="outsider@example.test",
        access_status=User.AccessStatus.ACTIVE,
    )
    response = authed(outsider).post(
        walk_in_url(space), {"display_name": "Nobody"}, format="json"
    )
    assert response.status_code in (403, 404)
    assert not User.objects.filter(display_name="Nobody").exists()
