"""A7 end to end: the staff path works module-off at EVERY step; the community path at none.

`test_membership_module_gating.py` pins the invitation itself. These pin what happens next:
the queue, the claim, the approval and the decline -- which used to dead-end a staff
invitation issued with the module off, and leave a community invitation or a referral
claimable after the module was switched off.
"""
from decimal import Decimal

import pytest
from django.urls import reverse

from apps.makerspaces import member_card_services, membership_services
from apps.makerspaces.models import (
    MakerspaceMembership,
    MembershipPlan,
    MembershipRequest,
)
from apps.makerspaces.module_install import install_module
from tests.makerspaces.test_membership_module_gating import (
    client_for,
    manager,
    role,
    space,
    user,
)
from tests.module_helpers import disable_module

pytestmark = pytest.mark.django_db(transaction=True)


def _queue(client, makerspace):
    response = client.get(reverse("admin-membership-requests"), {"makerspace_id": makerspace.pk})
    assert response.status_code == 200, response.data
    return [row["id"] for row in response.data["results"]]


def test_a_staff_invitation_issued_module_off_is_listed_claimed_and_approved():
    off = space("a7-staff-approve", membership_enabled=False)
    boss = manager(off, "a7-staff-approve-manager")
    invitee = user("a7-staff-approve-invitee")
    staff_role = role(off, "inventory_manager")
    invitation = membership_services.invite_membership(boss, off, invitee.email, staff_role)

    invitee_client = client_for(invitee)
    discovered = invitee_client.get(reverse("membership-invitations")).data["invitations"]
    assert [row["id"] for row in discovered] == [invitation.pk]
    claim = invitee_client.post(reverse("membership-invitation-claim", args=[invitation.pk]))
    assert claim.status_code == 200 and claim.data["outcome"] == "pending_approval"

    client = client_for(boss)
    assert _queue(client, off) == [invitation.pk]
    approved = client.post(
        reverse("admin-membership-request-approve", args=[invitation.pk]),
        {"role_id": staff_role.pk}, format="json",
    )

    assert approved.status_code == 200, approved.data
    membership = MakerspaceMembership.objects.get(makerspace=off, user=invitee)
    assert membership.status == "active" and membership.assigned_role == staff_role


def test_a_staff_invitation_can_be_declined_module_off():
    off = space("a7-staff-decline", membership_enabled=False)
    boss = manager(off, "a7-staff-decline-manager")
    invitation = membership_services.invite_membership(
        boss, off, "a7-decline@example.test", role(off, "inventory_manager")
    )

    response = client_for(boss).post(
        reverse("admin-membership-request-revoke", args=[invitation.pk]),
        {"reason": "Filled the post"}, format="json",
    )

    assert response.status_code == 200, response.data
    invitation.refresh_from_db()
    assert invitation.state == MembershipRequest.State.REVOKED
    assert invitation.decision_note == "Filled the post"


def test_module_off_queue_hides_community_rows_and_refuses_to_decide_them():
    makerspace = space("a7-queue", membership_enabled=True)
    boss = manager(makerspace, "a7-queue-manager")
    joiner = user("a7-queue-joiner")
    join = membership_services.request_membership(joiner, makerspace)
    community = membership_services.invite_membership(
        boss, makerspace, "a7-community@example.test", role(makerspace, "member")
    )
    staff = membership_services.invite_membership(
        boss, makerspace, "a7-staff@example.test", role(makerspace, "inventory_manager")
    )
    disable_module(makerspace, "membership")
    client = client_for(boss)

    assert _queue(client, makerspace) == [staff.pk]
    for request_id in (join.id, community.pk):
        assert client.post(
            reverse("admin-membership-request-approve", args=[request_id]),
            {"role_id": role(makerspace, "member").pk}, format="json",
        ).status_code == 400
        assert client.post(
            reverse("admin-membership-request-revoke", args=[request_id]), {}, format="json",
        ).status_code == 400


def test_approving_a_staff_invitation_into_a_role_with_no_actions_is_gated():
    # That outcome is a community member, so it is the module's business.
    off = space("a7-staff-to-member", membership_enabled=False)
    boss = manager(off, "a7-staff-to-member-manager")
    invitee = user("a7-staff-to-member-invitee")
    invitation = membership_services.invite_membership(
        boss, off, invitee.email, role(off, "inventory_manager")
    )

    response = client_for(boss).post(
        reverse("admin-membership-request-approve", args=[invitation.pk]),
        {"role_id": role(off, "member").pk}, format="json",
    )

    assert response.status_code == 400
    assert "module" in response.data
    assert not MakerspaceMembership.objects.filter(makerspace=off, user=invitee).exists()


def test_a_plan_on_approval_needs_the_module_even_for_a_staff_invitation():
    makerspace = space("a7-plan-off", membership_enabled=True)
    boss = manager(makerspace, "a7-plan-off-manager")
    invitee = user("a7-plan-off-invitee")
    plan = MembershipPlan.objects.create(
        makerspace=makerspace, name="Monthly", interval="monthly", amount=Decimal("5"),
    )
    staff_role = role(makerspace, "inventory_manager")
    invitation = membership_services.invite_membership(boss, makerspace, invitee.email, staff_role)
    disable_module(makerspace, "membership")

    response = client_for(boss).post(
        reverse("admin-membership-request-approve", args=[invitation.pk]),
        {"role_id": staff_role.pk, "plan_id": plan.pk}, format="json",
    )

    assert response.status_code == 400
    assert not MakerspaceMembership.objects.filter(makerspace=makerspace, user=invitee).exists()


def test_an_approval_whose_term_is_refused_does_not_leave_an_active_member():
    makerspace = space("a7-plan-rollback", membership_enabled=True)
    boss = manager(makerspace, "a7-plan-rollback-manager")
    joiner = user("a7-plan-rollback-joiner")
    join = membership_services.request_membership(joiner, makerspace)
    plan = MembershipPlan.objects.create(
        makerspace=makerspace, name="Old", interval="monthly", amount=Decimal("5"), is_active=False,
    )

    response = client_for(boss).post(
        reverse("admin-membership-request-approve", args=[join.id]),
        {"role_id": role(makerspace, "member").pk, "plan_id": plan.pk}, format="json",
    )

    assert response.status_code == 400
    assert not MakerspaceMembership.objects.filter(makerspace=makerspace, user=joiner).exists()
    assert MembershipRequest.objects.get(pk=join.id).state == MembershipRequest.State.REQUESTED


@pytest.mark.parametrize("kind", ["community", "referral"])
def test_a_community_invitation_stops_being_claimable_when_the_module_goes_off(kind):
    makerspace = space(f"a7-claim-{kind}", membership_enabled=True)
    boss = manager(makerspace, f"a7-claim-{kind}-manager")
    invitee = user(f"a7-claim-{kind}-invitee")
    if kind == "community":
        invitation = membership_services.invite_membership(
            boss, makerspace, invitee.email, role(makerspace, "member")
        )
    else:
        makerspace.referrals_enabled = True
        makerspace.save(update_fields=["referrals_enabled"])
        referrer = user(f"a7-claim-{kind}-referrer")
        MakerspaceMembership.objects.create(
            makerspace=makerspace, user=referrer, assigned_role=role(makerspace, "member"),
            role="custom",
        )
        invitation = membership_services.refer_membership(referrer, makerspace, invitee.email)
    disable_module(makerspace, "membership")
    client = client_for(invitee)

    discovered = client.get(reverse("membership-invitations")).data["invitations"]
    claim = client.post(reverse("membership-invitation-claim", args=[invitation.pk]))

    assert invitation.pk not in [row["id"] for row in discovered]
    assert claim.status_code == 400
    assert not MakerspaceMembership.objects.filter(makerspace=makerspace, user=invitee).exists()

    install_module(makerspace, "membership")
    assert client.post(
        reverse("membership-invitation-claim", args=[invitation.pk])
    ).status_code == 200


def test_member_card_reissue_revoke_and_print_are_gated_like_issue():
    makerspace = space("a7-cards", membership_enabled=True)
    boss = manager(makerspace, "a7-cards-manager")
    holder = MakerspaceMembership.objects.create(
        makerspace=makerspace, user=user("a7-cards-holder"),
        assigned_role=role(makerspace, "member"), role="custom",
    )
    card = member_card_services.issue_card(boss, holder, printed_name="Ada")
    disable_module(makerspace, "membership")
    client = client_for(boss)

    assert client.post(
        reverse("admin-member-card-reissue", kwargs={"pk": card.pk}), {"reason": "lost"}, format="json",
    ).status_code == 400
    assert client.post(reverse("admin-member-card-print", kwargs={"pk": card.pk})).status_code == 400
    assert client.post(
        reverse("admin-member-card-revoke", kwargs={"pk": card.pk}), {}, format="json",
    ).status_code == 400
    card.refresh_from_db()
    assert card.revoked_at is None and card.print_count == 0
