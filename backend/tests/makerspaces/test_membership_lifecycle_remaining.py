"""Remaining enrolment/delegation audit rows and the audit's D4/D6 defaults."""
import pytest
from django.core.cache import cache
from django.urls import reverse
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.throttling import ScopedRateThrottle

from apps.audit.models import AuditLog
from apps.accounts.models import User
from apps.makerspaces import membership_services
from apps.makerspaces.models import Makerspace, MakerspaceMembership, MembershipPlan, MembershipRequest, MembershipTerm
from tests.makerspaces.test_membership_j1 import manager, member_role, space, user
from tests.return_helpers import authenticated_client

pytestmark = pytest.mark.django_db


def test_request_policy_refuses_an_active_member_without_creating_a_request():
    makerspace = space("request-already-active")
    person = user("request-already-active-person")
    MakerspaceMembership.objects.create(makerspace=makerspace, user=person, assigned_role=member_role(makerspace), role="custom")
    with pytest.raises(ValidationError, match="already an active member"):
        membership_services.request_membership(person, makerspace)
    assert not MembershipRequest.objects.filter(makerspace=makerspace).exists()


def test_public_join_throttle_limits_writes(monkeypatch):
    makerspace = space("membership-throttle")
    person = user("membership-throttle-person")
    monkeypatch.setattr(ScopedRateThrottle, "THROTTLE_RATES", {**ScopedRateThrottle.THROTTLE_RATES, "membership_request": "1/hour"})
    cache.clear()
    try:
        client = authenticated_client(person)
        url = reverse("public-membership-request", args=[makerspace.slug])
        assert client.post(url, {}, format="json").status_code == 201
        response = client.post(url, {}, format="json")
        assert response.status_code == 429
        assert MembershipRequest.objects.filter(makerspace=makerspace).count() == 1
    finally:
        cache.clear()


@pytest.mark.parametrize("field,value", [("is_active", False), ("access_status", User.AccessStatus.RESTRICTED), ("access_status", User.AccessStatus.SUSPENDED)])
def test_join_refuses_inactive_or_restricted_identity_with_403(field, value):
    makerspace = space("join-inactive-identity")
    person = user("join-inactive-identity-person")
    setattr(person, field, value); person.save(update_fields=[field])
    response = authenticated_client(person).post(reverse("public-membership-request", args=[makerspace.slug]), {}, format="json")
    assert response.status_code == 403
    assert not MembershipRequest.objects.filter(makerspace=makerspace).exists()
    assert not AuditLog.objects.filter(action="membership.requested", actor=person).exists()


def test_invitation_role_must_belong_to_this_space_over_http():
    home, other = space("invite-role-home"), space("invite-role-other")
    boss = manager(home, "invite-role-manager")
    response = authenticated_client(boss).post(reverse("admin-membership-invitations", args=[home.pk]), {"role_id": member_role(other).pk, "invite_email": "visitor@example.test"}, format="json")
    assert response.status_code == 404
    assert not MembershipRequest.objects.filter(makerspace=home).exists()


def test_claim_service_refuses_wrong_email_non_invite_and_closed_invitation():
    makerspace = space("claim-invalid-state")
    boss = manager(makerspace, "claim-invalid-manager")
    person, stranger = user("claim-owner"), user("claim-stranger")
    invite = membership_services.invite_membership(boss, makerspace, person.email, member_role(makerspace))
    with pytest.raises(PermissionDenied):
        membership_services.claim_invitation(stranger, invite.pk)
    invite.state = MembershipRequest.State.REVOKED; invite.save(update_fields=["state"])
    with pytest.raises(ValidationError):
        membership_services.claim_invitation(person, invite.pk)
    requested = membership_services.request_membership(person, makerspace)
    with pytest.raises(ValidationError):
        membership_services.claim_invitation(person, requested.id)


@pytest.mark.parametrize("field", ["can_refer", "can_verify"])
def test_delegation_mutations_record_actor_target_and_value(field):
    makerspace = space(f"delegation-audit-{field}")
    boss = manager(makerspace, f"delegation-boss-{field}")
    row = MakerspaceMembership.objects.create(makerspace=makerspace, user=user(f"delegate-{field}"), assigned_role=member_role(makerspace), role="custom")
    response = authenticated_client(boss).patch(reverse("admin-membership-capabilities", args=[row.pk]), {field: True}, format="json")
    assert response.status_code == 200
    entry = AuditLog.objects.get(action=f"membership.{field}_changed", makerspace=makerspace)
    assert entry.actor == boss and entry.meta == {"value": True}
    assert response.data[field] is True


def test_reactivation_keeps_historical_verification_but_resets_delegations():
    makerspace = space("verification-reactivation", membership_policy=Makerspace.MembershipPolicy.OPEN)
    boss = manager(makerspace, "verification-reactivation-manager")
    person = user("verification-reactivation-member")
    outcome = membership_services.request_membership(person, makerspace)
    row = MakerspaceMembership.objects.get(pk=outcome["membership_id"])
    membership_services.verify_member(boss, row)
    row.refresh_from_db(); verified_at = row.verified_at
    membership_services.revoke_membership(boss, row, "Away")
    membership_services.request_membership(person, makerspace)
    row.refresh_from_db()
    assert row.verified_at == verified_at and row.verified_by == boss
    assert not row.can_verify and not row.can_refer


def test_open_join_never_implicitly_attaches_an_existing_plan():
    makerspace = space("open-no-default-plan", membership_policy=Makerspace.MembershipPolicy.OPEN)
    MembershipPlan.objects.create(makerspace=makerspace, name="Priced", interval="monthly", amount="20")
    outcome = membership_services.request_membership(user("open-no-default-plan-person"), makerspace)
    assert not MembershipTerm.objects.filter(membership_id=outcome["membership_id"]).exists()
