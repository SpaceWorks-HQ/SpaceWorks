"""Membership module gating (plan A7).

`MakerspaceMembership` is core RBAC state, so the `membership` module gates the
*community* membership feature only. Over-gating would lock a makerspace out of its
own staff administration -- the failure this file exists to prevent.
"""

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.makerspaces import membership_services
from apps.makerspaces.models import (
    Makerspace,
    MakerspaceMembership,
    MakerspaceRole,
    MakerspaceWaiver,
)
from apps.makerspaces.module_install import install_module, uninstall_module

pytestmark = pytest.mark.django_db(transaction=True)


def user(name):
    item = User.objects.create_user(
        username=name, email=f"{name}@example.test", password="password"
    )
    item.email_verified_at = timezone.now()
    item.save(update_fields=["email_verified_at"])
    return item


def space(slug, *, membership_enabled):
    item = Makerspace.objects.create(name=slug.title(), slug=slug)
    if membership_enabled:
        install_module(item, "membership")
    else:
        uninstall_module(item, "membership")
    item.refresh_from_db()
    return item


def role(makerspace, slug):
    return MakerspaceRole.objects.get(makerspace=makerspace, slug=slug)


def manager(makerspace, name):
    actor = user(name)
    MakerspaceMembership.objects.create(
        makerspace=makerspace, user=actor,
        assigned_role=role(makerspace, "space_manager"),
        role=MakerspaceMembership.Role.SPACE_MANAGER, status="active",
    )
    return actor


def client_for(actor):
    client = APIClient()
    client.force_authenticate(user=actor)
    return client


# --- the module gates the community feature ---------------------------------


def test_public_join_request_is_gated():
    off = space("join-off", membership_enabled=False)
    applicant = user("join-applicant")

    response = client_for(applicant).post(
        reverse("public-membership-request", kwargs={"makerspace_slug": off.slug}),
        {}, format="json",
    )

    assert response.status_code == 400
    assert "module" in response.data


def test_public_join_request_works_when_installed():
    on = space("join-on", membership_enabled=True)
    applicant = user("join-applicant-ok")

    response = client_for(applicant).post(
        reverse("public-membership-request", kwargs={"makerspace_slug": on.slug}),
        {}, format="json",
    )

    assert response.status_code == 201


def test_referrals_are_gated_even_when_referrals_enabled_is_set():
    # The module gate is additive: it must not be satisfied by, or replace, the
    # existing referrals_enabled readiness check.
    off = space("refer-off", membership_enabled=False)
    off.referrals_enabled = True
    off.save(update_fields=["referrals_enabled"])
    actor = user("referrer")
    MakerspaceMembership.objects.create(
        makerspace=off, user=actor, assigned_role=role(off, "member"),
        status="active", can_refer=True,
    )

    with pytest.raises(ValidationError) as exc:
        membership_services.refer_membership(actor, off, "friend@example.test")
    assert "module" in exc.value.detail


def test_request_queue_and_decisions_are_gated():
    off = space("queue-off", membership_enabled=False)
    staff = manager(off, "queue-manager")
    client = client_for(staff)

    listed = client.get(reverse("admin-membership-requests"), {"makerspace_id": off.id})

    assert listed.status_code == 400
    assert "module" in listed.data


def test_verify_and_unverify_are_gated():
    off = space("verify-off", membership_enabled=False)
    staff = manager(off, "verify-manager")
    target = MakerspaceMembership.objects.create(
        makerspace=off, user=user("verify-target"),
        assigned_role=role(off, "member"), status="active",
    )
    client = client_for(staff)

    for name in ("admin-membership-verify", "admin-membership-unverify"):
        response = client.post(reverse(name, kwargs={"pk": target.pk}))
        assert response.status_code == 400, name
        assert "module" in response.data


def test_member_waiver_read_and_accept_are_core_but_community_surfaces_stay_gated():
    off = space("waiver-off", membership_enabled=False)
    member = user("waiver-member")
    membership = MakerspaceMembership.objects.create(
        makerspace=off, user=member, assigned_role=role(off, "member"), status="active",
    )
    waiver_record = MakerspaceWaiver.objects.create(
        makerspace=off, version="v1", body="Mind the laser.", is_active=True,
    )
    client = client_for(member)

    waiver = client.get(reverse("member-waiver", kwargs={"makerspace_id": off.id}))
    accept = client.post(reverse("member-waiver-accept", kwargs={"makerspace_id": off.id}))
    activity = client.get(reverse("member-activity", kwargs={"makerspace_id": off.id}))
    profile = client.get(reverse("member-profile", kwargs={"makerspace_id": off.id}))
    directory = client.get(reverse("member-directory", kwargs={"makerspace_id": off.id}))

    assert waiver.status_code == 200
    assert waiver.data == {
        "has_waiver": True,
        "body": waiver_record.body,
        "version": waiver_record.version,
    }
    assert accept.status_code == 200
    membership.refresh_from_db()
    assert membership.accepted_waiver_id == waiver_record.id
    assert activity.status_code == 400
    assert profile.status_code == 400
    assert directory.status_code == 400


# --- core RBAC state is NEVER gated -----------------------------------------


def test_staff_roster_and_my_memberships_survive_without_the_module():
    off = space("roster-off", membership_enabled=False)
    staff = manager(off, "roster-manager")
    client = client_for(staff)

    roster = client.get(reverse("admin-memberships-roster"), {"makerspace_id": off.id})
    mine = client.get(reverse("my-memberships"))

    assert roster.status_code == 200
    assert mine.status_code == 200


def test_membership_list_create_and_role_assignment_survive_without_the_module():
    off = space("admin-off", membership_enabled=False)
    staff = manager(off, "admin-manager")
    client = client_for(staff)
    target = user("admin-target")

    created = client.post(
        reverse("admin-membership-list-create", kwargs={"makerspace_id": off.id}),
        # Any role that grants actions makes this a *staff* invitation, which is the path
        # under test. Machine Manager rather than the old Guest Admin: 0052 retired that
        # seeded role, and what matters here is only that the role grants something.
        {"username": target.username, "role_id": role(off, "machine_manager").id},
        format="json",
    )
    assert created.status_code in (200, 201), created.data

    membership = MakerspaceMembership.objects.get(makerspace=off, user=target)
    reassigned = client.patch(
        reverse("admin-membership-role-m2", kwargs={"pk": membership.pk}),
        {"role_id": role(off, "inventory_manager").id},
        format="json",
    )
    assert reassigned.status_code == 200

    capabilities = client.patch(
        reverse("admin-membership-capabilities", kwargs={"pk": membership.pk}),
        {"can_refer": True}, format="json",
    )
    assert capabilities.status_code == 200

    revoked = client.post(
        reverse("admin-membership-revoke-m2", kwargs={"pk": membership.pk}),
        {"reason": "done"}, format="json",
    )
    assert revoked.status_code == 200


# --- invitations discriminate by intent -------------------------------------


def test_staff_invitation_works_without_the_module():
    # A staff invitation assigns a role granting actions. Gating it would strand a
    # makerspace that never enabled community membership but still needs staff.
    off = space("invite-staff", membership_enabled=False)
    staff = manager(off, "invite-staff-manager")

    invitation = membership_services.invite_membership(
        staff, off, "new-staff@example.test", role(off, "inventory_manager")
    )

    assert invitation.pk is not None
    assert invitation.assigned_role.granted_actions


def test_community_invitation_is_gated():
    off = space("invite-member", membership_enabled=False)
    staff = manager(off, "invite-member-manager")

    with pytest.raises(ValidationError) as exc:
        membership_services.invite_membership(
            staff, off, "new-member@example.test", role(off, "member")
        )
    assert "module" in exc.value.detail


def test_community_invitation_works_once_the_module_is_installed():
    on = space("invite-member-on", membership_enabled=True)
    staff = manager(on, "invite-member-on-manager")

    invitation = membership_services.invite_membership(
        staff, on, "new-member@example.test", role(on, "member")
    )

    assert invitation.pk is not None


def test_intent_is_decided_by_granted_actions_not_role_slug():
    # A custom role granting no actions is a community role however it is named, so
    # it must be gated the same way the protected Member role is.
    off = space("invite-custom", membership_enabled=False)
    staff = manager(off, "invite-custom-manager")
    hangers_on = MakerspaceRole.objects.create(
        makerspace=off, slug="friends", name="Friends", granted_actions=[]
    )

    with pytest.raises(ValidationError):
        membership_services.invite_membership(
            staff, off, "friend@example.test", hangers_on
        )
