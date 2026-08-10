"""Phase 11 -- the security pass over the module-architecture program.

Every check here corresponds to a finding or an accepted risk in
`docs/module-program-security-report.md`. They are written as assertions rather than
prose because a boundary nobody tests is a boundary that quietly moves.
"""

import pytest
from rest_framework.test import APIClient

from apps.accounts import rbac
from apps.accounts.models import PlatformLoginMethods, User
from apps.inventory.public_image_storage import build_object_key
from apps.makerspaces import profile_services
from apps.makerspaces.models import (
    Makerspace,
    MakerspaceMembership,
    MakerspaceRole,
    MemberProfile,
)
from apps.makerspaces.walk_in_services import create_walk_in_member

pytestmark = pytest.mark.django_db

PASSWORD = "Safe audit password 947!"


def make_space(slug):
    return Makerspace.objects.create(name=slug, slug=slug)


def staffer(makerspace, slug="inventory_manager", username="auditor"):
    user = User.objects.create_user(
        username=f"{username}-{makerspace.slug}",
        email=f"{username}-{makerspace.slug}@example.test",
        password=PASSWORD,
        access_status=User.AccessStatus.ACTIVE,
    )
    role = MakerspaceRole.objects.get(makerspace=makerspace, slug=slug)
    MakerspaceMembership.objects.create(
        user=user, makerspace=makerspace, role=role.legacy_role or MakerspaceMembership.Role.CUSTOM,
        assigned_role=role, status="active",
    )
    return user


def authed(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


# --- walk-in records ---------------------------------------------------------------


def test_a_walk_in_record_grants_no_authority_anywhere():
    """It names a person. It must not be a way to manufacture access."""
    space = make_space("walkin-authority")
    front_desk = staffer(space)
    membership = create_walk_in_member(front_desk, space, display_name="Walk In")

    assert membership.assigned_role.granted_actions == []
    for action in (
        rbac.Action.ISSUE_DIRECT_LOAN, rbac.Action.EDIT_INVENTORY,
        rbac.Action.MANAGE_MAKERSPACE, rbac.Action.VIEW_AUDIT,
    ):
        assert rbac.can(membership.user, action, space.pk) is False
    assert membership.user.is_staff is False
    assert membership.user.is_superuser is False
    assert membership.user.role == User.Role.REQUESTER


def test_a_walk_in_record_cannot_be_signed_into():
    space = make_space("walkin-login")
    front_desk = staffer(space)
    membership = create_walk_in_member(
        front_desk, space, display_name="Walk In", email="walkin@example.test"
    )

    assert membership.user.has_usable_password() is False
    # Not merely "no password set" — the login endpoint must actually refuse. An empty
    # string, a blank body and the unusable-password marker must all fail.
    client = APIClient()
    for attempt in ("", " ", "!"):
        response = client.post(
            "/api/v1/auth/login",
            {"username": membership.user.username, "password": attempt},
            format="json",
        )
        # 400 for a blank credential, 401 for a wrong one — the property under test is
        # that no input signs this record in.
        assert response.status_code in (400, 401), attempt


def test_a_walk_in_is_confined_to_the_makerspace_that_created_it():
    space = make_space("walkin-scope-a")
    other = make_space("walkin-scope-b")
    front_desk = staffer(space)
    membership = create_walk_in_member(front_desk, space, display_name="Walk In")

    assert not MakerspaceMembership.objects.filter(
        user=membership.user, makerspace=other
    ).exists()
    assert rbac.makerspaces_for_action(
        membership.user, rbac.Action.VIEW_INVENTORY
    ) in (set(), frozenset())


def test_walk_in_creation_is_charged_against_the_member_quota():
    """Otherwise the front desk is an unmetered way past a managed plan's limits."""
    from apps.makerspaces import limits

    space = make_space("walkin-quota")
    front_desk = staffer(space)
    calls = []
    original = limits.check_quota

    def spy(makerspace, key, *, adding=1):
        calls.append(key)
        return original(makerspace, key, adding=adding)

    limits.check_quota = spy
    try:
        create_walk_in_member(front_desk, space, display_name="Walk In")
    finally:
        limits.check_quota = original
    assert "members" in calls


# --- maker profiles ----------------------------------------------------------------


def member_of(makerspace, username):
    user = User.objects.create_user(
        username=f"{username}-{makerspace.slug}",
        email=f"{username}-{makerspace.slug}@example.test",
        phone="+15550100100",
        display_name=username.title(),
        access_status=User.AccessStatus.ACTIVE,
    )
    return MakerspaceMembership.objects.create(
        user=user, makerspace=makerspace, role=MakerspaceMembership.Role.CUSTOM,
        assigned_role=MakerspaceRole.objects.get(makerspace=makerspace, slug="member"),
        status="active",
    )


def test_a_profile_image_key_from_another_makerspace_is_refused():
    """The prefix check is what stops one tenant attaching another tenant's object."""
    space = make_space("image-scope-a")
    other = make_space("image-scope-b")
    membership = member_of(space, "owner")
    foreign_key = build_object_key("member", other.pk, ".png")

    response = authed(membership.user).put(
        f"/api/v1/member/makerspaces/{space.pk}/profile/image",
        {"object_key": foreign_key},
        format="json",
    )
    assert response.status_code == 400
    assert "object_key" in response.data


def test_a_member_cannot_edit_another_members_project():
    space = make_space("project-owner")
    mine = member_of(space, "mine")
    theirs = member_of(space, "theirs")
    their_profile = profile_services.profile_for(theirs)
    profile_services.save_projects(their_profile, [{"title": "Theirs"}])
    their_project = their_profile.projects.get()

    response = authed(mine.user).put(
        f"/api/v1/member/makerspaces/{space.pk}/profile",
        {"projects": [{"id": their_project.pk, "title": "Hijacked"}]},
        format="json",
    )
    assert response.status_code == 400
    their_project.refresh_from_db()
    assert their_project.title == "Theirs"


def test_publishing_a_profile_never_publishes_contact_details():
    space = make_space("profile-pii")
    subject = member_of(space, "subject")
    viewer = member_of(space, "viewer")
    profile_services.save_profile(subject, {"is_visible": True, "bio": "Hello"})

    payload = authed(viewer.user).get(
        f"/api/v1/member/makerspaces/{space.pk}/directory/{subject.pk}"
    ).data
    serialized = str(payload)
    assert subject.user.email not in serialized
    assert subject.user.phone not in serialized


def test_a_member_of_another_space_cannot_read_this_directory():
    space = make_space("directory-a")
    other = make_space("directory-b")
    subject = member_of(space, "subject")
    outsider = member_of(other, "outsider")
    profile_services.save_profile(subject, {"is_visible": True})

    assert authed(outsider.user).get(
        f"/api/v1/member/makerspaces/{space.pk}/directory"
    ).status_code == 403
    assert authed(outsider.user).get(
        f"/api/v1/member/makerspaces/{space.pk}/directory/{subject.pk}"
    ).status_code == 403


def test_a_revoked_member_disappears_from_the_directory():
    space = make_space("directory-revoked")
    subject = member_of(space, "subject")
    viewer = member_of(space, "viewer")
    profile_services.save_profile(subject, {"is_visible": True})
    assert authed(viewer.user).get(
        f"/api/v1/member/makerspaces/{space.pk}/directory"
    ).data["members"]

    subject.status = "revoked"
    subject.save(update_fields=["status"])

    listing = authed(viewer.user).get(
        f"/api/v1/member/makerspaces/{space.pk}/directory"
    ).data
    assert listing["members"] == []
    # And not merely hidden from the list — the detail route closes too.
    assert authed(viewer.user).get(
        f"/api/v1/member/makerspaces/{space.pk}/directory/{subject.pk}"
    ).status_code == 404


def test_a_suspended_account_cannot_reach_its_own_profile():
    space = make_space("profile-suspended")
    membership = member_of(space, "suspended")
    membership.user.access_status = User.AccessStatus.RESTRICTED
    membership.user.save(update_fields=["access_status"])

    assert authed(membership.user).get(
        f"/api/v1/member/makerspaces/{space.pk}/profile"
    ).status_code == 403


def test_profile_links_reject_every_scheme_but_http():
    space = make_space("profile-schemes")
    membership = member_of(space, "author")
    client = authed(membership.user)

    for url in ("javascript:alert(1)", "data:text/html,<script>", "vbscript:x", "file:///etc/passwd"):
        response = client.put(
            f"/api/v1/member/makerspaces/{space.pk}/profile",
            {"projects": [{"title": "X", "links": [{"label": "Go", "url": url}]}]},
            format="json",
        )
        assert response.status_code == 400, url


# --- login-method switches ---------------------------------------------------------


def test_disabling_passwords_does_not_revoke_a_live_session():
    """Documented, accepted behaviour: a switch is a policy change, not a revocation."""
    space = make_space("session-survival")
    user = staffer(space)
    client = APIClient()
    signed_in = client.post(
        "/api/v1/auth/login", {"username": user.username, "password": PASSWORD}, format="json"
    )
    assert signed_in.status_code == 200

    PlatformLoginMethods.objects.update_or_create(
        pk=1,
        defaults={
            "password_enabled": False, "social_enabled": True,
            "phone_enabled": True, "self_registration_enabled": True,
        },
    )
    # New sign-ins are refused...
    assert client.post(
        "/api/v1/auth/login", {"username": user.username, "password": PASSWORD}, format="json"
    ).status_code == 403
    # ...while the token already issued keeps working. Revoking sessions is the
    # restrict/suspend flow's job, not a login-method switch's.
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {signed_in.data['access']}")
    assert client.get("/api/v1/auth/me").status_code == 200


def test_the_switch_row_is_never_written_by_an_anonymous_request():
    """A read path that writes is a write per unauthenticated login attempt."""
    APIClient().get("/api/v1/config")
    APIClient().post(
        "/api/v1/auth/login", {"username": "nobody", "password": "x"}, format="json"
    )
    assert not PlatformLoginMethods.objects.exists()


# --- module gating -----------------------------------------------------------------


def test_uninstalling_membership_closes_the_profile_surfaces_but_keeps_the_data():
    from apps.makerspaces.module_install import uninstall_module

    space = make_space("profile-uninstall")
    membership = member_of(space, "author")
    profile_services.save_profile(membership, {"is_visible": True, "bio": "Kept"})
    uninstall_module(space, "membership")

    client = authed(membership.user)
    assert client.get(f"/api/v1/member/makerspaces/{space.pk}/profile").status_code == 400
    assert client.get(f"/api/v1/member/makerspaces/{space.pk}/directory").status_code == 400
    # Uninstall hides; only a purge destroys.
    assert MemberProfile.objects.get(membership=membership).bio == "Kept"
