"""The protected Member role is the community seam, so it cannot be widened or re-slugged.

Every open join, referral claim, walk-in and imported adoption activates onto the role with
slug `member`, and `invite_membership` reads "grants no actions" as "community invitation".
Before this file a Space Manager could grant the Member role an action (turning all of
those into staff grants and the community gate into a bypass) or rename it (which re-slugged
it, so every one of those paths then failed with "no protected Member role").
"""
import pytest
from rest_framework.exceptions import ValidationError

from apps.makerspaces import membership_services, role_services
from apps.makerspaces.models import Makerspace, MakerspaceRole
from tests.makerspaces.test_membership_j1 import manager, space, user

pytestmark = pytest.mark.django_db


def _member_role(makerspace):
    return MakerspaceRole.objects.get(makerspace=makerspace, slug="member")


def test_the_member_role_cannot_be_granted_an_action():
    makerspace = space("member-role-actions")
    actor = manager(makerspace, "member-role-actions-manager")

    with pytest.raises(ValidationError) as exc:
        role_services.update_role(
            makerspace=makerspace, role=_member_role(makerspace), actor=actor,
            granted_actions=["view_inventory"],
        )

    assert "granted_actions" in exc.value.detail
    assert _member_role(makerspace).granted_actions == []


def test_renaming_the_member_role_keeps_its_slug_and_joining_still_works():
    makerspace = space("member-role-rename", membership_policy=Makerspace.MembershipPolicy.OPEN)
    actor = manager(makerspace, "member-role-rename-manager")

    renamed = role_services.update_role(
        makerspace=makerspace, role=_member_role(makerspace), actor=actor, name="Community",
    )
    joined = membership_services.request_membership(user("member-role-rename-joiner"), makerspace)

    assert (renamed.name, renamed.slug) == ("Community", "member")
    assert joined["outcome"] == "joined"


def test_a_custom_role_is_still_re_slugged_on_rename_and_may_hold_actions():
    makerspace = space("member-role-custom")
    actor = manager(makerspace, "member-role-custom-manager")
    custom = role_services.create_role(
        makerspace=makerspace, actor=actor, name="Front Desk", granted_actions=["view_inventory"],
    )

    renamed = role_services.update_role(
        makerspace=makerspace, role=custom, actor=actor, name="Counter",
        granted_actions=["view_inventory", "issue_direct_loan"],
    )

    assert renamed.slug == "counter"
    assert sorted(renamed.granted_actions) == ["issue_direct_loan", "view_inventory"]
