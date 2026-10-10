"""Directory search/404 parity, profile bounds, image audits and GitHub command."""
from io import StringIO

import pytest
from django.core.management import call_command
from django.urls import reverse

from apps.audit.models import AuditLog
from apps.inventory import public_image_storage
from apps.makerspaces import profile_images, profile_services
from apps.makerspaces.models import MemberProfile, MemberProject
from tests.makerspaces.test_member_profiles_p12 import make_space, member, authed

pytestmark = pytest.mark.django_db


def test_directory_search_matches_public_identity_and_detail_404_is_uniform():
    home, other = make_space("directory-search"), make_space("directory-foreign")
    viewer = member(home, "viewer")
    subject = member(home, "author", display_name="Ada")
    foreign = member(other, "foreign")
    profile_services.save_profile(subject, {"is_visible": True, "headline": "Robotics", "institution": "Lab"})
    profile_services.save_profile(foreign, {"is_visible": True})
    client = authed(viewer.user)
    url = reverse("member-directory", args=[home.pk])
    for query in ("ada", "ROBOTICS", "Lab"):
        assert [row["membership_id"] for row in client.get(url, {"q": query}).data["members"]] == [subject.pk]
    assert client.get(url, {"q": subject.user.email}).data["members"] == []
    unknown = client.get(reverse("member-directory-detail", args=[home.pk, 999999]))
    cross = client.get(reverse("member-directory-detail", args=[home.pk, foreign.pk]))
    assert unknown.status_code == cross.status_code == 404
    assert unknown.data == cross.data


@pytest.mark.parametrize("field,limit", [("headline", 200), ("institution", 200), ("bio", 2000)])
def test_profile_text_length_boundary_is_enforced_over_http(field, limit):
    makerspace = make_space(f"profile-limit-{field}")
    row = member(makerspace)
    client = authed(row.user); url = reverse("member-profile", args=[makerspace.pk])
    assert client.put(url, {field: "x" * limit}, format="json").status_code == 200
    assert client.put(url, {field: "x" * (limit + 1)}, format="json").status_code == 400
    assert getattr(MemberProfile.objects.get(membership=row), field) == "x" * limit


def test_avatar_and_project_image_updates_and_clears_are_audited_without_keys(monkeypatch):
    makerspace = make_space("profile-image-audits")
    row = member(makerspace)
    profile = profile_services.profile_for(row)
    project = MemberProject.objects.create(profile=profile, title="Project")
    monkeypatch.setattr(public_image_storage, "object_size", lambda key: 123)
    monkeypatch.setattr(public_image_storage, "release_public_image_on_commit", lambda *args: None)
    avatar_key = f"member/{makerspace.pk}/avatar.jpg"
    project_key = f"member/{makerspace.pk}/project.jpg"
    profile_images.set_avatar(profile, avatar_key)
    profile_images.set_project_image(profile, project, project_key)
    profile_images.set_avatar(profile, "")
    profile_images.set_project_image(profile, project, "")
    entries = AuditLog.objects.filter(actor=row.user, makerspace=makerspace, action__in=["member.profile_image_updated", "member.profile_image_cleared"])
    assert entries.count() == 4
    assert {entry.meta["kind"] for entry in entries} == {"avatar", "project"}
    assert avatar_key not in str(list(entries.values_list("meta", flat=True)))
    assert project_key not in str(list(entries.values_list("meta", flat=True)))


def test_github_command_skips_fresh_profiles_and_continues_after_unavailable_profile(monkeypatch):
    makerspace = make_space("github-command")
    for name in ("fresh", "fail", "update"):
        MemberProfile.objects.create(membership=member(makerspace, name), github_username=name)
    from apps.makerspaces import github_contributions
    monkeypatch.setattr(github_contributions, "is_configured", lambda: True)
    monkeypatch.setattr(github_contributions, "due_for_sync", lambda profile: profile.github_username != "fresh")
    calls = []
    def refresh(profile):
        calls.append(profile.github_username)
        return profile.github_username != "fail"
    monkeypatch.setattr(github_contributions, "refresh", refresh)
    output = StringIO(); call_command("refresh_github_contributions", stdout=output)
    assert sorted(calls) == ["fail", "update"]
    assert "updated=1 skipped=1 unavailable=1" in output.getvalue()
    calls.clear(); call_command("refresh_github_contributions", all=True, stdout=StringIO())
    assert sorted(calls) == ["fail", "fresh", "update"]
