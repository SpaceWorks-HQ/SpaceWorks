"""Delegated verification works with a real member JWT and stays tenant scoped."""
import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.accounts.claim_routes import policy_for
from apps.accounts.claim_route_types import Refused
from apps.accounts.tokens import SpaceWorksRefreshToken
from apps.audit.models import AuditLog
from apps.makerspaces.models import MakerspaceMembership
from tests.accounts.claim_helpers_p7 import redeemed_claim
from tests.makerspaces.test_membership_j1 import manager, member_role, space, user
from tests.module_helpers import disable_module
from tests.return_helpers import authenticated_client

pytestmark = pytest.mark.django_db


def member(makerspace, name, **kwargs):
    return MakerspaceMembership.objects.create(makerspace=makerspace, user=user(name), assigned_role=member_role(makerspace), role="custom", **kwargs)


def token_client(person):
    # Mint as login does: only the refresh token stamps the deployment auth generation.
    token = SpaceWorksRefreshToken.for_user(person).access_token
    token["surface"] = "member"
    client = APIClient(); client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return client


def test_delegate_verifies_and_unverifies_with_member_session_without_staff_roster_access():
    makerspace = space("delegate-http")
    delegate = member(makerspace, "delegate-http-verifier", can_verify=True)
    target = member(makerspace, "delegate-http-target")
    client = token_client(delegate.user)
    url = reverse("member-verification", args=[makerspace.pk])
    for verified, action in [(True, "membership.verified"), (False, "membership.unverified")]:
        response = client.post(url, {"membership_id": target.pk, "verified": verified}, format="json")
        assert response.status_code == 200, response.data
        assert set(response.data) == {"membership_id", "display_name", "verified_at"}
        target.refresh_from_db()
        assert bool(target.verified_at) is verified
        assert AuditLog.objects.filter(action=action, actor=delegate.user, makerspace=makerspace).exists()
    assert client.get(reverse("admin-memberships-roster"), {"makerspace_id": makerspace.pk}).status_code == 403
    assert client.post(reverse("admin-membership-verify", args=[target.pk])).status_code == 403


def test_delegate_cannot_verify_self_or_cross_tenant_target():
    home, other = space("delegate-home"), space("delegate-other")
    delegate = member(home, "delegate-scoped", can_verify=True)
    target = member(other, "delegate-foreign")
    client = token_client(delegate.user)
    url = reverse("member-verification", args=[home.pk])
    assert client.post(url, {"membership_id": delegate.pk, "verified": True}, format="json").status_code == 403
    assert client.post(url, {"membership_id": target.pk, "verified": True}, format="json").status_code == 404
    # Even a delegate holding authority in both spaces cannot mismatch path and target.
    member(other, "delegate-second")
    MakerspaceMembership.objects.create(makerspace=other, user=delegate.user, assigned_role=member_role(other), role="custom", can_verify=True)
    assert client.post(url, {"membership_id": target.pk, "verified": True}, format="json").status_code == 404
    assert not AuditLog.objects.filter(action="membership.verified").exists()


def test_verification_refuses_revoked_targets_lost_delegation_and_module_off():
    makerspace = space("delegate-refusals")
    delegate = member(makerspace, "delegate-refusals-verifier", can_verify=True)
    target = member(makerspace, "delegate-refusals-target", status="revoked")
    client = token_client(delegate.user)
    url = reverse("member-verification", args=[makerspace.pk])
    payload = {"membership_id": target.pk, "verified": True}
    assert client.post(url, payload, format="json").status_code == 400
    MakerspaceMembership.objects.filter(pk=target.pk).update(status="active")
    disable_module(makerspace, "membership")
    assert client.post(url, payload, format="json").status_code == 400
    MakerspaceMembership.objects.filter(pk=delegate.pk).update(can_verify=False)
    assert client.post(url, payload, format="json").status_code == 404
    assert not AuditLog.objects.filter(action="membership.verified").exists()


def test_claim_session_is_explicitly_refused_on_verification():
    harness = redeemed_claim("verification-refused")
    assert isinstance(policy_for("member-verification", "POST"), Refused)
    response = harness.claim_client.post(reverse("member-verification", args=[harness.space.pk]), {"membership_id": harness.membership.pk, "verified": True}, format="json")
    assert response.status_code == 403


@pytest.mark.parametrize("body", [{}, {"membership_id": 0, "verified": True}, {"membership_id": "bad", "verified": True}, {"membership_id": 1, "verified": "bad"}])
def test_verification_validates_payload_before_lookup_or_mutation(body):
    makerspace = space("delegate-invalid")
    delegate = member(makerspace, "delegate-invalid-verifier", can_verify=True)
    response = token_client(delegate.user).post(reverse("member-verification", args=[makerspace.pk]), body, format="json")
    assert response.status_code == 400
    assert not AuditLog.objects.filter(action="membership.verified").exists()


def test_staff_reads_and_deactivates_current_waiver_module_off_with_tenant_scope():
    makerspace = space("waiver-staff-read")
    other = space("waiver-staff-foreign")
    boss = manager(makerspace, "waiver-staff-read-manager")
    client = authenticated_client(boss)
    disable_module(makerspace, "membership")
    url = reverse("admin-makerspace-waiver", args=[makerspace.pk])
    assert client.get(url).data == {"has_waiver": False}
    assert client.put(url, {"body": "Safety terms", "version": "v1"}, format="json").status_code == 200
    assert client.get(url).data == {"has_waiver": True, "body": "Safety terms", "version": "v1"}
    assert client.get(reverse("admin-makerspace-waiver", args=[other.pk])).status_code == 404
    assert client.put(url, {"clear": True}, format="json").status_code == 200
    assert client.get(url).data == {"has_waiver": False}
    assert AuditLog.objects.filter(action="makerspace.waiver_deactivated", actor=boss, makerspace=makerspace).exists()
