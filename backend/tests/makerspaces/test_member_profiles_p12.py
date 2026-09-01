"""Phase 12 -- maker profiles, and the three registrations that fail silently if missed.

The feature is easy; the invariants around it are not. A public image that no collector
knows about outlives every row that could name it, a purge that forgets the profile
leaves community content behind after the module was destroyed, and a directory that
lists everyone publishes people who never agreed to be published.
"""

import pytest
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.inventory.public_image_storage import (
    build_object_key,
    public_image_key_in_use,
)
from apps.makerspaces import profile_services
from apps.makerspaces.models import (
    Makerspace,
    MakerspaceMembership,
    MakerspaceRole,
    MemberProfile,
    MemberProject,
)

pytestmark = pytest.mark.django_db


def make_space(slug="profile-space"):
    return Makerspace.objects.create(name=slug, slug=slug)


def member(makerspace, username="profile-member", display_name="Ada Lovelace"):
    user = User.objects.create_user(
        username=f"{username}-{makerspace.slug}",
        email=f"{username}-{makerspace.slug}@example.test",
        display_name=display_name,
        access_status=User.AccessStatus.ACTIVE,
    )
    return MakerspaceMembership.objects.create(
        user=user, makerspace=makerspace, role=MakerspaceMembership.Role.CUSTOM,
        assigned_role=MakerspaceRole.objects.get(makerspace=makerspace, slug="member"),
        status="active",
    )


def authed(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def profile_url(makerspace):
    return f"/api/v1/member/makerspaces/{makerspace.id}/profile"


def directory_url(makerspace):
    return f"/api/v1/member/makerspaces/{makerspace.id}/directory"


# --- the surface ------------------------------------------------------------------


def test_a_member_writes_their_own_profile_and_reads_it_back():
    space = make_space()
    membership = member(space)

    response = authed(membership.user).put(
        profile_url(space),
        {
            "is_visible": True,
            "headline": "Embedded systems",
            "institution": "Some College",
            "bio": "I build small robots.",
            "interests": ["robotics", "cnc"],
            "languages": ["Malayalam", "English"],
            "education": [{"institution": "Some College", "qualification": "BTech", "year": "2024"}],
            "projects": [
                {
                    "title": "Line follower",
                    "description": "A small robot.",
                    "links": [{"label": "Repo", "url": "https://example.test/repo"}],
                }
            ],
        },
        format="json",
    )
    assert response.status_code == 200, response.data
    assert response.data["display_name"] == "Ada Lovelace"
    assert response.data["interests"] == ["robotics", "cnc"]
    assert len(response.data["projects"]) == 1
    assert response.data["projects"][0]["title"] == "Line follower"


def test_a_javascript_link_is_refused():
    """These render as an href on a page other members read."""
    space = make_space()
    membership = member(space)

    response = authed(membership.user).put(
        profile_url(space),
        {"projects": [{"title": "X", "links": [{"label": "Go", "url": "javascript:alert(1)"}]}]},
        format="json",
    )
    assert response.status_code == 400


def test_lists_are_capped():
    space = make_space()
    membership = member(space)

    response = authed(membership.user).put(
        profile_url(space),
        {"interests": [f"tag-{index}" for index in range(50)]},
        format="json",
    )
    assert response.status_code == 400


def test_saving_projects_replaces_the_list_and_rejects_a_foreign_id():
    space = make_space()
    membership = member(space)
    client = authed(membership.user)
    client.put(
        profile_url(space),
        {"projects": [{"title": "First"}, {"title": "Second"}]},
        format="json",
    )
    kept = MemberProject.objects.get(title="First")

    # Sending only one back deletes the other: with a merge there is no way to express
    # removing a project at all.
    response = client.put(
        profile_url(space), {"projects": [{"id": kept.pk, "title": "First renamed"}]},
        format="json",
    )
    assert response.status_code == 200
    assert list(MemberProject.objects.values_list("title", flat=True)) == ["First renamed"]

    # A foreign id is a 400, never a silent drop.
    other = member(make_space("other-space"), username="other-member")
    foreign = MemberProject.objects.create(
        profile=profile_services.profile_for(other), title="Theirs"
    )
    response = client.put(
        profile_url(space), {"projects": [{"id": foreign.pk, "title": "Stolen"}]},
        format="json",
    )
    assert response.status_code == 400
    foreign.refresh_from_db()
    assert foreign.title == "Theirs"


def test_changing_the_github_handle_drops_the_cached_count():
    """Otherwise one account's total shows under another account's name."""
    space = make_space()
    membership = member(space)
    profile = profile_services.profile_for(membership)
    MemberProfile.objects.filter(pk=profile.pk).update(
        github_username="first", github_contributions=1234
    )

    authed(membership.user).put(
        profile_url(space), {"github_username": "second"}, format="json"
    )
    profile.refresh_from_db()
    assert profile.github_username == "second"
    assert profile.github_contributions is None


# --- privacy ----------------------------------------------------------------------


def test_the_directory_lists_only_opted_in_members_and_counts_the_rest():
    space = make_space()
    shown = member(space, username="shown", display_name="Shown Person")
    hidden = member(space, username="hidden", display_name="Hidden Person")
    viewer = member(space, username="viewer", display_name="Viewer")
    profile_services.save_profile(shown, {"is_visible": True, "headline": "Welder"})
    profile_services.save_profile(hidden, {"is_visible": False})

    response = authed(viewer.user).get(directory_url(space))
    assert response.status_code == 200
    listed = response.data["members"]
    assert [row["display_name"] for row in listed] == ["Shown Person"]
    # The viewer and the hidden member both count; neither is named.
    assert response.data["hidden_count"] == 2


def test_a_directory_row_never_carries_contact_details():
    space = make_space()
    shown = member(space, username="shown", display_name="Shown Person")
    viewer = member(space, username="viewer")
    profile_services.save_profile(shown, {"is_visible": True})

    row = authed(viewer.user).get(directory_url(space)).data["members"][0]
    assert set(row) == {"membership_id", "display_name", "headline", "avatar_url"}


def test_an_unpublished_profile_is_a_404_to_another_member():
    space = make_space()
    hidden = member(space, username="hidden")
    viewer = member(space, username="viewer")
    profile_services.save_profile(hidden, {"is_visible": False, "bio": "private"})

    response = authed(viewer.user).get(f"{directory_url(space)}/{hidden.pk}")
    assert response.status_code == 404


def test_a_non_member_reaches_nothing():
    space = make_space()
    member(space)
    outsider = User.objects.create_user(
        username="outsider", email="outsider@example.test",
        access_status=User.AccessStatus.ACTIVE,
    )

    assert authed(outsider).get(profile_url(space)).status_code == 403
    assert authed(outsider).get(directory_url(space)).status_code == 403


def test_the_directory_needs_the_membership_module():
    from apps.makerspaces.module_install import uninstall_module
    from tests.module_helpers import disable_module

    space = make_space()
    viewer = member(space, username="viewer")
    disable_module(space, "membership")

    # The typed `module` 400 every other module gate raises, not a permission error:
    # the caller is allowed here, the space just does not run the module.
    response = authed(viewer.user).get(directory_url(space))
    assert response.status_code == 400
    assert "module" in response.data


# --- the registrations that fail silently -----------------------------------------


def test_the_member_image_kind_is_allowed():
    key = build_object_key("member", 7, ".png")
    assert key.startswith("member/7/")


def test_a_key_claimed_by_one_profile_cannot_be_attached_to_another():
    """Clearing the first would delete the object and blank the second."""
    space = make_space()
    first = profile_services.profile_for(member(space, username="first"))
    second = profile_services.profile_for(member(space, username="second"))
    key = build_object_key("member", space.id, ".png")
    MemberProfile.objects.filter(pk=first.pk).update(avatar_key=key)

    assert public_image_key_in_use(space.id, key, profile_id=second.pk) is True
    # ...but the holder may re-attach its own key without tripping the check.
    assert public_image_key_in_use(space.id, key, profile_id=first.pk) is False


def test_a_project_image_key_is_seen_by_the_collision_check():
    space = make_space()
    profile = profile_services.profile_for(member(space))
    key = build_object_key("member", space.id, ".png")
    project = MemberProject.objects.create(profile=profile, title="P", image_key=key)

    assert public_image_key_in_use(space.id, key) is True
    assert public_image_key_in_use(space.id, key, project_id=project.pk) is False


def test_every_collector_sees_member_imagery():
    """Three collectors, all of which fail OPEN — a miss strands the object silently."""
    from apps.makerspaces.lifecycle import _collect_public_image_keys
    from apps.makerspaces.management.commands.recompute_storage import Command
    from apps.makerspaces.module_purge_collectors import membership_public_image_keys

    space = make_space()
    profile = profile_services.profile_for(member(space))
    avatar = build_object_key("member", space.id, ".png")
    project_key = build_object_key("member", space.id, ".jpg")
    MemberProfile.objects.filter(pk=profile.pk).update(avatar_key=avatar)
    MemberProject.objects.create(profile=profile, title="P", image_key=project_key)

    assert {avatar, project_key} <= set(_collect_public_image_keys(space))
    assert {avatar, project_key} <= set(Command._public_image_keys(space))
    assert {avatar, project_key} <= set(membership_public_image_keys(space))


def test_a_membership_purge_destroys_profiles_but_keeps_the_membership():
    from apps.makerspaces.module_purge_collectors import membership_delete

    space = make_space()
    membership = member(space)
    profile = profile_services.profile_for(membership)
    MemberProject.objects.create(profile=profile, title="P")

    membership_delete(space, None)

    assert not MemberProfile.objects.filter(pk=profile.pk).exists()
    assert not MemberProject.objects.exists(), "projects cascade from the profile"
    # Core RBAC state, deliberately left behind (plan A7).
    assert MakerspaceMembership.objects.filter(pk=membership.pk).exists()


def test_the_membership_plan_declares_its_imagery():
    from apps.makerspaces.module_purge_plans import BY_KEY

    # Without this the purge deletes the rows and leaves the objects unnameable.
    assert BY_KEY["membership"].public_image_keys is not None


# --- GitHub -----------------------------------------------------------------------


def test_github_is_dormant_without_a_token(settings):
    from apps.makerspaces import github_contributions

    settings.GITHUB_API_TOKEN = ""
    space = make_space()
    membership = member(space)
    profile_services.save_profile(membership, {"github_username": "octocat"})
    profile = profile_services.profile_for(membership)

    assert github_contributions.is_configured() is False
    assert github_contributions.due_for_sync(profile) is False
    assert github_contributions.fetch_total("octocat") is None


def test_a_failed_fetch_keeps_the_last_known_count(settings, monkeypatch):
    """A rate-limited GitHub must never blank a profile."""
    from apps.makerspaces import github_contributions

    settings.GITHUB_API_TOKEN = "token"
    space = make_space()
    membership = member(space)
    profile = profile_services.profile_for(membership)
    MemberProfile.objects.filter(pk=profile.pk).update(
        github_username="octocat", github_contributions=987
    )
    profile.refresh_from_db()

    monkeypatch.setattr(github_contributions, "fetch_total", lambda login: None)
    assert github_contributions.refresh(profile) is False

    profile.refresh_from_db()
    assert profile.github_contributions == 987
    # Stamped even on failure, so a broken API backs off instead of being retried on
    # every pass.
    assert profile.github_synced_at is not None
    assert github_contributions.due_for_sync(profile) is False


def test_a_transport_failure_is_swallowed(settings, monkeypatch):
    import urllib.request

    from apps.makerspaces import github_contributions

    settings.GITHUB_API_TOKEN = "token"

    def explode(*args, **kwargs):
        raise OSError("connection reset")

    monkeypatch.setattr(urllib.request, "urlopen", explode)
    assert github_contributions.fetch_total("octocat") is None


def test_profile_reads_never_call_github(settings, monkeypatch):
    """The read path must not depend on an external service being up at all."""
    import urllib.request

    settings.GITHUB_API_TOKEN = "token"
    space = make_space()
    membership = member(space)
    profile_services.save_profile(membership, {"github_username": "octocat"})

    def explode(*args, **kwargs):
        raise AssertionError("a profile read must never reach out to GitHub")

    monkeypatch.setattr(urllib.request, "urlopen", explode)
    assert authed(membership.user).get(profile_url(space)).status_code == 200


def test_save_projects_rejects_a_foreign_id_before_writing_anything():
    space = make_space()
    membership = member(space)
    profile = profile_services.profile_for(membership)

    with pytest.raises(ValidationError):
        profile_services.save_projects(profile, [{"title": "New"}, {"id": 999, "title": "X"}])
