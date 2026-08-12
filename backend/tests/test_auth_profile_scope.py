import pytest
from django.utils import timezone
from rest_framework.test import APIClient, APIRequestFactory, force_authenticate

from apps.accounts import rbac
from apps.accounts.models import User
from apps.accounts.serializers import user_payload
from apps.accounts.views import MeView
from apps.makerspaces.models import Makerspace, MakerspaceMembership
from tests.return_helpers import make_space, make_user

pytestmark = pytest.mark.django_db

LOGIN = "/api/v1/auth/login"


def _make_staff_with_memberships(username="profile-scope-staff"):
    space_a = make_space(f"{username}-a")
    space_a.frontend_domain = "a.example"
    space_a.frontend_domain_status = Makerspace.DomainStatus.VERIFIED
    space_a.save(update_fields=["frontend_domain", "frontend_domain_status"])
    space_b = make_space(f"{username}-b")
    archived = make_space(f"{username}-archived")
    archived.frontend_domain = "archived.example"
    archived.archived_at = timezone.now()
    archived.save(update_fields=["frontend_domain", "archived_at"])
    user = make_user(
        username,
        role=User.Role.SPACE_MANAGER,
        access_status=User.AccessStatus.ACTIVE,
        password="pw-strong-123",
    )
    for makerspace in (space_a, space_b, archived):
        MakerspaceMembership.objects.create(
            user=user,
            makerspace=makerspace,
            role=MakerspaceMembership.Role.SPACE_MANAGER,
        )
    return user, space_a, space_b, archived


def _membership_ids(payload):
    return {row["id"] for row in payload["makerspaces"]}


def test_user_payload_scopes_memberships_to_branded_staff_origin_and_excludes_archived():
    user, space_a, space_b, archived = _make_staff_with_memberships("payload-scope")
    request = APIRequestFactory().get("/api/v1/auth/me", HTTP_ORIGIN="https://a.example")

    payload = user_payload(user, request=request)

    assert _membership_ids(payload) == {space_a.id}
    assert archived.id not in _membership_ids(payload)
    assert payload["makerspaces"] == [
        {
            "id": space_a.id,
            "slug": space_a.slug,
            "role": MakerspaceMembership.Role.SPACE_MANAGER,
            "role_id": None,
                "role_name": "Space Manager",
                "role_slug": MakerspaceMembership.Role.SPACE_MANAGER,
                "actions": sorted(rbac.effective_actions(user, space_a.id)),
                "can_configure_machine_types": True,
                # A space manager is scope-EXEMPT, so the console keeps every surface.
                "is_machine_only": False,
                "can_refer": True,
                "can_verify": False,
                "verified_at": None,
                "referrals_enabled": False,
            }
        ]


def test_user_payload_without_origin_keeps_all_non_archived_memberships():
    user, space_a, space_b, archived = _make_staff_with_memberships("payload-central")
    request = APIRequestFactory().get("/api/v1/auth/me")

    payload = user_payload(user, request=request)

    assert _membership_ids(payload) == {space_a.id, space_b.id}
    assert archived.id not in _membership_ids(payload)


def test_me_view_scopes_memberships_to_branded_staff_origin():
    user, space_a, _space_b, _archived = _make_staff_with_memberships("me-scope")
    request = APIRequestFactory().get("/api/v1/auth/me", HTTP_ORIGIN="https://a.example")
    force_authenticate(request, user=user)

    response = MeView.as_view()(request)

    assert response.status_code == 200
    assert _membership_ids(response.data) == {space_a.id}


def test_login_response_scopes_memberships_to_branded_staff_origin():
    user, space_a, _space_b, _archived = _make_staff_with_memberships("login-scope")

    response = APIClient().post(
        LOGIN,
        {"username": user.username, "password": "pw-strong-123"},
        format="json",
        HTTP_ORIGIN="https://a.example",
    )

    assert response.status_code == 200
    assert _membership_ids(response.data["user"]) == {space_a.id}
    assert "access" in response.data
    assert "refresh" not in response.data


def test_hidden_makerspace_staff_keeps_own_profile_membership():
    hidden = make_space("profile-hidden-own")
    hidden.frontend_domain = "hidden.example"
    hidden.frontend_domain_status = Makerspace.DomainStatus.VERIFIED
    hidden.superadmin_access_enabled = False
    hidden.save(
        update_fields=[
            "frontend_domain",
            "frontend_domain_status",
            "superadmin_access_enabled",
        ]
    )
    user = make_user(
        "profile-hidden-manager",
        role=User.Role.SPACE_MANAGER,
        access_status=User.AccessStatus.ACTIVE,
    )
    MakerspaceMembership.objects.create(
        user=user,
        makerspace=hidden,
        role=MakerspaceMembership.Role.SPACE_MANAGER,
    )
    request = APIRequestFactory().get("/api/v1/auth/me", HTTP_ORIGIN="https://hidden.example")

    payload = user_payload(user, request=request)

    assert _membership_ids(payload) == {hidden.id}
