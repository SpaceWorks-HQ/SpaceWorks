from types import SimpleNamespace

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.makerspaces.models import (
    Makerspace,
    MakerspaceMembership,
    MakerspaceRole,
    MemberProfile,
)

pytestmark = pytest.mark.django_db


def member_and_client():
    space = Makerspace.objects.create(name="Profile split", slug="profile-split")
    user = User.objects.create_user(
        username="profile-split-member",
        email="profile-split@example.test",
        access_status=User.AccessStatus.ACTIVE,
    )
    membership = MakerspaceMembership.objects.create(
        user=user,
        makerspace=space,
        role=MakerspaceMembership.Role.CUSTOM,
        assigned_role=MakerspaceRole.objects.get(makerspace=space, slug="member"),
        status="active",
    )
    client = APIClient()
    client.force_authenticate(user=user)
    return space, membership, client


def profile_url(space):
    return f"/api/v1/member/makerspaces/{space.pk}/profile"


def test_profile_get_returns_defaults_without_creating_a_row():
    space, membership, client = member_and_client()

    response = client.get(profile_url(space))

    assert response.status_code == 200
    assert response.data["projects"] == []
    assert response.data["is_visible"] is False
    assert not MemberProfile.objects.filter(membership=membership).exists()


def test_profile_put_still_uses_the_write_side_creation_helper():
    space, membership, client = member_and_client()

    response = client.put(
        profile_url(space), {"headline": "Lathe learner"}, format="json"
    )

    assert response.status_code == 200
    assert MemberProfile.objects.get(membership=membership).headline == "Lathe learner"


def test_profile_image_put_and_delete_still_create_and_update_the_row(monkeypatch):
    space, membership, client = member_and_client()
    object_key = f"member/{space.pk}/avatar.png"
    monkeypatch.setattr(
        "apps.inventory.public_image_storage.finalize_upload",
        lambda _key: SimpleNamespace(status="ok"),
    )
    monkeypatch.setattr(
        "apps.inventory.public_image_storage.sniff_is_valid_image", lambda _key: True
    )
    monkeypatch.setattr(
        "apps.inventory.public_image_storage.object_size", lambda _key: 123
    )

    attached = client.put(
        f"{profile_url(space)}/image", {"object_key": object_key}, format="json"
    )

    assert attached.status_code == 200, attached.data
    profile = MemberProfile.objects.get(membership=membership)
    assert profile.avatar_key == object_key

    cleared = client.delete(f"{profile_url(space)}/image")

    assert cleared.status_code == 200, cleared.data
    profile.refresh_from_db()
    assert profile.avatar_key == ""
