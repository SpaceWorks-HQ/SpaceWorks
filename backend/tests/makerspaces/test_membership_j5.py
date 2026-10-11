import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.makerspaces import membership_services
from apps.makerspaces.models import Makerspace, MakerspaceMembership, MakerspaceRole


pytestmark = pytest.mark.django_db


def user(name, *, verified=True):
    person = User.objects.create_user(
        username=name, email=f"{name}@example.test", password="password"
    )
    if verified:
        person.email_verified_at = timezone.now()
        person.save(update_fields=["email_verified_at"])
    return person


def space(slug, **kwargs):
    return Makerspace.objects.create(name=slug.title(), slug=slug, **kwargs)


def member(person, makerspace, **kwargs):
    role = MakerspaceRole.objects.get(makerspace=makerspace, slug="member")
    return MakerspaceMembership.objects.create(
        user=person, makerspace=makerspace, assigned_role=role, role="custom", **kwargs
    )


def client_for(person):
    client = APIClient()
    client.force_authenticate(person)
    return client


def test_member_referral_route_enforces_enabled_capability_and_makerspace_scope(monkeypatch):
    referrals = space("j5-referrals", referrals_enabled=True)
    disabled = space("j5-disabled")
    referrer = user("j5-referrer")
    member(referrer, referrals)
    member(referrer, disabled)
    client = client_for(referrer)
    delivered = []
    monkeypatch.setattr(
        "apps.integrations.email.send_makerspace_email",
        lambda *args, **kwargs: delivered.append((args, kwargs)),
    )

    created = client.post(
        f"/api/v1/member/makerspaces/{referrals.id}/referrals",
        {"invite_email": "new-member@example.test"}, format="json",
    )
    assert created.status_code == 201
    assert created.data == {"state": "invited"}
    assert delivered == [(
        (referrals, "Makerspace membership invitation", "You have been invited to join this makerspace. Sign in with this email to claim the invitation.", ["new-member@example.test"]),
        {"stream": "membership", "event": "invitation", "audience": "member"},
    )]

    assert client.post(
        f"/api/v1/member/makerspaces/{disabled.id}/referrals",
        {"invite_email": "disabled@example.test"}, format="json",
    ).status_code == 403

    membership = MakerspaceMembership.objects.get(user=referrer, makerspace=referrals)
    membership.can_refer = False
    membership.save(update_fields=["can_refer"])
    assert client.post(
        f"/api/v1/member/makerspaces/{referrals.id}/referrals",
        {"invite_email": "delegated-off@example.test"}, format="json",
    ).status_code == 403

    outsider = user("j5-outsider")
    assert client_for(outsider).post(
        f"/api/v1/member/makerspaces/{referrals.id}/referrals",
        {"invite_email": "cross-space@example.test"}, format="json",
    ).status_code == 403


def test_invitation_portal_contract_hides_unverified_or_other_space_invitations_and_claims():
    first = space("j5-first", referrals_enabled=True)
    second = space("j5-second", referrals_enabled=True)
    referrer = user("j5-portal-referrer")
    member(referrer, first)
    referral = membership_services.refer_membership(referrer, first, "j5-invitee@example.test")
    other = membership_services.refer_membership(referrer, first, "j5-other@example.test")
    invitee = user("j5-invitee", verified=False)

    unverified = client_for(invitee)
    assert unverified.get("/api/v1/memberships/invitations").data == {"invitations": []}
    assert unverified.post(f"/api/v1/memberships/invitations/{referral.id}/claim").status_code == 404

    invitee.email_verified_at = timezone.now()
    invitee.save(update_fields=["email_verified_at"])
    discovered = client_for(invitee).get("/api/v1/memberships/invitations")
    assert discovered.status_code == 200
    assert discovered.data == {"invitations": [{
        "id": referral.id,
        "makerspace": {"slug": first.slug, "name": first.name},
        "inviter": referrer.display_name,
        "auto_activates": True,
        "role": "Member",
        "is_staff": False,
    }]}
    assert client_for(invitee).post(
        f"/api/v1/memberships/invitations/{referral.id}/claim"
    ).data == {"id": referral.id, "outcome": "active"}

    stranger = user("j5-stranger")
    assert client_for(stranger).post(
        f"/api/v1/memberships/invitations/{other.id}/claim"
    ).status_code == 404
    assert client_for(stranger).post(
        f"/api/v1/member/makerspaces/{second.id}/referrals",
        {"invite_email": "not-authorized@example.test"}, format="json",
    ).status_code == 403
