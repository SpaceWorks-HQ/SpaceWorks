import hashlib
import uuid

import pytest

from apps.accounts.models import User
from apps.makerspaces.models import (
    Makerspace,
    MakerspaceMembership,
    MemberProfile,
    MemberProject,
)
from apps.tenant_migration.object_export import object_member_path
from apps.tenant_migration.tenant_dump_objects import package_staged_objects
from apps.tenant_migration.tenant_dump_source_projection import project_makerspace_source


pytestmark = pytest.mark.django_db


def test_full_profile_project_consents_content_and_object_bytes_match_source(tmp_path):
    space = Makerspace.objects.create(name="D8 full profile", slug="d8-full-profile")
    user = User.objects.create_user(username="d8-full-profile-user")
    membership = MakerspaceMembership.objects.create(makerspace=space, user=user)
    profile = MemberProfile.objects.create(
        membership=membership,
        is_visible=True,
        show_attended_events=False,
        headline="Exact headline",
        institution="Exact institution",
        bio="Exact biography",
        avatar_key="profiles/d8-avatar.png",
        interests=["electronics", "woodwork"],
        languages=["en", "ml"],
        education="Exact education",
        github_username="exact-maker",
    )
    project = MemberProject.objects.create(
        profile=profile,
        title="Exact project",
        description="Exact description",
        image_key="projects/d8-project.png",
        links=[{"label": "Source", "url": "https://example.test/source"}],
        position=7,
    )

    projection = project_makerspace_source(space.pk, capture_id=uuid.uuid4())
    projected_profile = projection.rows["makerspaces.MemberProfile"][0]
    projected_project = projection.rows["makerspaces.MemberProject"][0]

    assert {
        key: projected_profile[key]
        for key in (
            "is_visible", "show_attended_events", "headline", "institution", "bio",
            "avatar_key", "interests", "languages", "education", "github_username",
        )
    } == {
        "is_visible": True,
        "show_attended_events": False,
        "headline": "Exact headline",
        "institution": "Exact institution",
        "bio": "Exact biography",
        "avatar_key": "profiles/d8-avatar.png",
        "interests": ["electronics", "woodwork"],
        "languages": ["en", "ml"],
        "education": "Exact education",
        "github_username": "exact-maker",
    }
    assert {
        key: projected_project[key]
        for key in ("title", "description", "image_key", "links", "position")
    } == {
        "title": "Exact project",
        "description": "Exact description",
        "image_key": "projects/d8-project.png",
        "links": [{"label": "Source", "url": "https://example.test/source"}],
        "position": 7,
    }
    assert projection.excluded_object_keys.isdisjoint(
        {profile.avatar_key, project.image_key}
    )

    payload = b"exact full-profile object bytes"
    member = object_member_path("public_image", profile.avatar_key)
    staged = tmp_path / "staged"
    staged.joinpath(member).parent.mkdir(parents=True)
    staged.joinpath(member).write_bytes(payload)
    bundle = tmp_path / "bundle"
    manifest = package_staged_objects(staged, bundle, ({
        "bucket_kind": "public_image",
        "source_key": profile.avatar_key,
        "member_path": str(member),
        "size": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    },))

    assert bundle.joinpath(manifest[0]["member_path"]).read_bytes() == payload
