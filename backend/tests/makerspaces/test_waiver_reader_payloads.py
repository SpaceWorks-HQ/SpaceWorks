import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.makerspaces.models import (
    Makerspace,
    MakerspaceMembership,
    MakerspaceRole,
    MakerspaceWaiver,
)
from apps.makerspaces.module_install import install_module

pytestmark = pytest.mark.django_db


def authed(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def membership(space, user, role_slug):
    role = MakerspaceRole.objects.get(makerspace=space, slug=role_slug)
    return MakerspaceMembership.objects.create(
        makerspace=space,
        user=user,
        assigned_role=role,
        role=role.legacy_role or MakerspaceMembership.Role.CUSTOM,
        status="active",
    )


def test_member_activity_listing_and_staff_roster_share_current_waiver_state():
    space = Makerspace.objects.create(name="Readers", slug="waiver-readers")
    install_module(space, "membership")
    manager = User.objects.create_user(username="reader-manager", password="password")
    member = User.objects.create_user(username="reader-member", password="password")
    membership(space, manager, "space_manager")
    target = membership(space, member, "member")
    waiver = MakerspaceWaiver.objects.create(
        makerspace=space, version="v1", body="Terms", is_active=True,
    )
    MakerspaceMembership.objects.filter(pk=target.pk).update(
        witnessed_waiver=waiver,
        witnessed_waiver_version=waiver.version,
        witnessed_by=manager,
        witnessed_at=timezone.now(),
    )

    mine = authed(member).get(reverse("my-memberships"))
    activity = authed(member).get(
        reverse("member-activity", kwargs={"makerspace_id": space.pk})
    )
    roster = authed(manager).get(
        reverse("admin-memberships-roster"), {"makerspace_id": space.pk}
    )

    assert mine.data["memberships"][0]["waiver_accepted"] is True
    assert mine.data["memberships"][0]["waiver_acceptance_required"] is False
    assert activity.data["accountability"]["waiver_acceptance_required"] is False
    target_row = next(row for row in roster.data["results"] if row["id"] == target.id)
    assert target_row["waiver_current"] is True

    waiver.is_active = False
    waiver.save(update_fields=["is_active"])
    MakerspaceWaiver.objects.create(
        makerspace=space, version="v2", body="New terms", is_active=True,
    )
    mine = authed(member).get(reverse("my-memberships"))
    activity = authed(member).get(
        reverse("member-activity", kwargs={"makerspace_id": space.pk})
    )
    roster = authed(manager).get(
        reverse("admin-memberships-roster"), {"makerspace_id": space.pk}
    )

    assert mine.data["memberships"][0]["waiver_accepted"] is True
    assert mine.data["memberships"][0]["waiver_acceptance_required"] is True
    assert activity.data["accountability"]["waiver_acceptance_required"] is True
    target_row = next(row for row in roster.data["results"] if row["id"] == target.id)
    assert target_row["waiver_current"] is False
