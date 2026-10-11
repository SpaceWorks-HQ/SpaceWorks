"""Membership decisions, reactivation and role changes preserve lifecycle history."""
import pytest
from django.urls import reverse

from apps.audit.models import AuditLog
from apps.makerspaces import membership_services
from apps.makerspaces.models import Makerspace, MakerspaceMembership, MakerspaceRole, MembershipRequest
from tests.makerspaces.test_membership_j1 import manager, member_role, space, user
from tests.makerspaces.test_membership_matrix_actors import _client

pytestmark = pytest.mark.django_db(transaction=True)


def test_declining_a_join_request_records_the_note_and_is_audited():
    makerspace = space("actors-decline")
    boss = manager(makerspace, "actors-decline-manager")
    join = membership_services.request_membership(user("actors-decline-joiner"), makerspace)

    response = _client(boss).post(
        reverse("admin-membership-request-revoke", args=[join.id]), {"reason": "Full this term"}, format="json",
    )

    assert response.status_code == 200
    request = MembershipRequest.objects.get(pk=join.id)
    assert (request.state, request.decision_note) == (MembershipRequest.State.REVOKED, "Full this term")
    assert request.decided_at is not None
    assert AuditLog.objects.filter(action="membership.revoked", makerspace=makerspace).exists()


def test_reactivation_clears_the_revocation_record():
    makerspace = space("actors-reactivate", membership_policy=Makerspace.MembershipPolicy.OPEN)
    boss = manager(makerspace, "actors-reactivate-manager")
    member = user("actors-reactivate-member")
    membership_services.request_membership(member, makerspace)
    membership = MakerspaceMembership.objects.get(makerspace=makerspace, user=member)
    membership_services.revoke_membership(boss, membership, "Paused")
    membership.refresh_from_db()
    assert (membership.revoked_by_id, membership.revocation_reason) == (boss.pk, "Paused")

    membership_services.request_membership(member, makerspace)

    membership.refresh_from_db()
    assert membership.status == "active"
    assert (membership.revoked_at, membership.revoked_by_id, membership.revocation_reason) == (None, None, "")


def test_a_revoked_membership_cannot_change_role_or_be_verified():
    from rest_framework.exceptions import ValidationError

    makerspace = space("actors-revoked-edits")
    boss = manager(makerspace, "actors-revoked-edits-manager")
    membership = MakerspaceMembership.objects.create(
        makerspace=makerspace, user=user("actors-revoked-edits-member"),
        assigned_role=member_role(makerspace), role="custom", status="revoked",
    )

    with pytest.raises(ValidationError):
        membership_services.change_role(boss, membership, member_role(makerspace))
    with pytest.raises(ValidationError):
        membership_services.verify_member(boss, membership)


def test_a_role_change_is_audited():
    makerspace = space("actors-role-audit")
    boss = manager(makerspace, "actors-role-audit-manager")
    membership = MakerspaceMembership.objects.create(
        makerspace=makerspace, user=user("actors-role-audit-member"),
        assigned_role=member_role(makerspace), role="custom",
    )
    inventory = MakerspaceRole.objects.get(makerspace=makerspace, slug="inventory_manager")

    membership_services.change_role(boss, membership, inventory)

    entry = AuditLog.objects.get(action="membership.role_changed", makerspace=makerspace)
    assert entry.meta == {"role_id": inventory.pk}
