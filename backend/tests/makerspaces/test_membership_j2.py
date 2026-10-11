import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.makerspaces import membership_services
from apps.makerspaces.models import Makerspace, MakerspaceMembership, MakerspaceRole


pytestmark = pytest.mark.django_db


def user(name, *, verified=True):
    item = User.objects.create_user(
        username=name, email=f"{name}@example.test", password="password"
    )
    if verified:
        item.email_verified_at = timezone.now()
        item.save(update_fields=["email_verified_at"])
    return item


def space(slug, **kwargs):
    return Makerspace.objects.create(name=slug.title(), slug=slug, **kwargs)


def role(makerspace, slug):
    return MakerspaceRole.objects.get(makerspace=makerspace, slug=slug)


def membership(person, makerspace, role_slug="member", **kwargs):
    assigned = role(makerspace, role_slug)
    return MakerspaceMembership.objects.create(
        user=person,
        makerspace=makerspace,
        assigned_role=assigned,
        role=assigned.legacy_role or MakerspaceMembership.Role.CUSTOM,
        **kwargs,
    )


def manager(makerspace, name="manager"):
    person = user(name)
    membership(person, makerspace, "space_manager")
    return person


def client_for(person):
    client = APIClient()
    client.force_authenticate(person)
    return client


def test_manager_settings_validate_policy_and_public_bootstrap_keeps_referrals_private():
    makerspace = space("j2-default")
    actor = manager(makerspace)
    client = client_for(actor)

    response = client.patch(
        f"/api/v1/admin/makerspaces/{makerspace.id}",
        {"membership_policy": "open", "referrals_enabled": True},
        format="json",
    )
    assert response.status_code == 200
    assert response.data["membership_policy"] == "open"
    assert response.data["referrals_enabled"] is True
    assert client.patch(
        f"/api/v1/admin/makerspaces/{makerspace.id}",
        {"membership_policy": "not-a-policy"}, format="json"
    ).status_code == 400

    default_bootstrap = APIClient().get("/api/v1/bootstrap?slug=j2-default")
    assert default_bootstrap.status_code == 200
    assert default_bootstrap.data["makerspace"]["membership_policy"] == "open"
    assert "referrals_enabled" not in default_bootstrap.data["makerspace"]


def test_invitation_discovery_is_verified_email_owner_safe_and_claims_by_outcome():
    makerspace = space("j2-invites", referrals_enabled=True)
    actor = manager(makerspace)
    invitee = user("j2-invitee", verified=False)
    manager_invite = membership_services.invite_membership(
        actor, makerspace, invitee.email, role(makerspace, "member")
    )
    client = client_for(invitee)

    assert client.get("/api/v1/memberships/invitations").data == {"invitations": []}
    assert client.post(f"/api/v1/memberships/invitations/{manager_invite.id}/claim").status_code == 404

    invitee.email_verified_at = timezone.now()
    invitee.save(update_fields=["email_verified_at"])
    discovered = client.get("/api/v1/memberships/invitations")
    assert discovered.status_code == 200
    invitation = discovered.data["invitations"][0]
    assert invitation["id"] == manager_invite.id
    assert invitation["makerspace"] == {"slug": makerspace.slug, "name": makerspace.name}
    assert set(invitation) == {"id", "makerspace", "inviter", "auto_activates", "role", "is_staff"}
    assert invitation["is_staff"] is False
    assert client.post(f"/api/v1/memberships/invitations/{manager_invite.id}/claim").data == {
        "id": manager_invite.id,
        "outcome": "pending_approval",
    }

    referral_invitee = user("j2-referral-invitee")
    referral_invite = membership_services.refer_membership(actor, makerspace, referral_invitee.email)
    claimed = client_for(referral_invitee).post(
        f"/api/v1/memberships/invitations/{referral_invite.id}/claim"
    )
    assert claimed.status_code == 200
    assert claimed.data == {"id": referral_invite.id, "outcome": "active"}

    stranger = user("j2-stranger")
    assert client_for(stranger).post(
        f"/api/v1/memberships/invitations/{manager_invite.id}/claim"
    ).status_code == 404


def test_capabilities_and_verification_are_scoped_and_service_backed():
    makerspace = space("j2-staff")
    foreign = space("j2-foreign")
    actor = manager(makerspace)
    delegate = user("j2-delegate")
    delegate_membership = membership(delegate, makerspace)
    target = membership(user("j2-target"), makerspace)
    foreign_target = membership(user("j2-foreign-target"), foreign)
    client = client_for(actor)

    updated = client.patch(
        f"/api/v1/admin/memberships/{delegate_membership.id}/capabilities",
        {"can_refer": False, "can_verify": True}, format="json",
    )
    assert updated.status_code == 200
    assert updated.data["can_refer"] is False and updated.data["can_verify"] is True
    assert client.post(f"/api/v1/admin/memberships/{foreign_target.id}/verify").status_code == 404

    delegate_client = client_for(delegate)
    verified = delegate_client.post(f"/api/v1/admin/memberships/{target.id}/verify")
    assert verified.status_code == 200
    assert verified.data["verified_at"] is not None
    assert delegate_client.post(
        f"/api/v1/admin/memberships/{delegate_membership.id}/verify"
    ).status_code == 403
    assert client.post(f"/api/v1/admin/memberships/{target.id}/unverify").status_code == 200


def test_own_membership_fields_do_not_appear_in_staff_safe_bootstrap_or_public_request_shape():
    makerspace = space("j2-own", referrals_enabled=True)
    person = user("j2-own-user")
    own = membership(person, makerspace, can_refer=False, can_verify=True)
    own.verified_at = timezone.now()
    own.save(update_fields=["verified_at"])

    auth = client_for(person).get("/api/v1/auth/me")
    payload = auth.data["makerspaces"][0]
    assert {"can_refer", "can_verify", "verified_at", "referrals_enabled"} <= set(payload)
    assert payload["can_refer"] is False and payload["referrals_enabled"] is True

    mine = client_for(person).get("/api/v1/memberships/me")
    assert {"can_refer", "can_verify", "verified_at", "referrals_enabled"} <= set(mine.data["memberships"][0])

    request = client_for(user("j2-requester")).post(
        f"/api/v1/public/{makerspace.slug}/membership-requests", {}, format="json"
    )
    assert request.status_code == 201
    assert request.data["outcome"] == "requested"
    assert "can_refer" not in request.data
