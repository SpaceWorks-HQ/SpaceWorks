"""Matrix cells M4–M6, M9, M22–M26 and the lifecycle rows the audit found untested.

Who may act (anonymous, a stranger, front-desk staff, a Space Manager, an
organization-conferred manager) and what approval costs (free, priced plan, one-off dues,
both) -- pinned through the HTTP surface staff and members actually use.
"""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts import rbac
from apps.audit.models import AuditLog
from apps.makerspaces import membership_services
from apps.makerspaces.membership_plan_services import run_membership_renewals
from apps.makerspaces.models import (
    Makerspace,
    MakerspaceMembership,
    MakerspaceRole,
    MembershipPlan,
    MembershipRequest,
    MembershipTerm,
)
from apps.organizations.models import Organization, OrganizationMakerspace, OrganizationMembership
from apps.payments.models import Payment
from tests.handout_roles import make_handout_member
from tests.makerspaces.test_membership_j1 import manager, member_role, space, user
from tests.makerspaces.test_membership_matrix import TRACKING, _features

pytestmark = pytest.mark.django_db(transaction=True)


def _client(actor=None):
    client = APIClient()
    if actor is not None:
        client.force_authenticate(actor)
    return client


def _approve(actor, request_id, role, **extra):
    return _client(actor).post(
        reverse("admin-membership-request-approve", args=[request_id]),
        {"role_id": role.pk, **extra}, format="json",
    )


def _join_url(makerspace):
    return reverse("public-membership-request", args=[makerspace.slug])


# ------------------------------------------------------------- M22 / M9: the public side


def test_an_anonymous_visitor_cannot_send_a_join_request():
    makerspace = space("actors-anonymous")

    assert _client().post(_join_url(makerspace), {}, format="json").status_code == 401
    assert not MembershipRequest.objects.filter(makerspace=makerspace).exists()


def test_an_invite_only_space_refuses_the_join_request_over_http():
    makerspace = space("actors-invite-only", membership_policy=Makerspace.MembershipPolicy.INVITE_ONLY)

    response = _client(user("actors-invite-only-joiner")).post(_join_url(makerspace), {}, format="json")

    assert response.status_code == 400
    assert not MembershipRequest.objects.filter(makerspace=makerspace).exists()


def test_a_duplicate_join_request_and_an_inactive_account_are_refused():
    makerspace = space("actors-duplicate")
    joiner = user("actors-duplicate-joiner")
    assert _client(joiner).post(_join_url(makerspace), {}, format="json").status_code == 201

    assert _client(joiner).post(_join_url(makerspace), {}, format="json").status_code == 400
    inactive = user("actors-duplicate-inactive")
    inactive.is_active = False
    inactive.save(update_fields=["is_active"])
    assert _client(inactive).post(_join_url(makerspace), {}, format="json").status_code in (401, 403)
    assert MembershipRequest.objects.filter(makerspace=makerspace).count() == 1


# ------------------------------------------------------ M4–M6: what approval costs


def test_approving_a_free_join_request_welcomes_the_member(monkeypatch):
    emails = []
    monkeypatch.setattr(
        "apps.makerspaces.membership_notifications.send_makerspace_email",
        lambda *args, **kwargs: emails.append(kwargs.get("event")),
    )
    makerspace = space("actors-approve-free")
    boss = manager(makerspace, "actors-approve-free-manager")
    joiner = user("actors-approve-free-joiner")
    join = membership_services.request_membership(joiner, makerspace)

    response = _approve(boss, join.id, member_role(makerspace))

    assert response.status_code == 200, response.data
    assert response.data["status"] == "active"
    assert "approved" in emails
    assert not Payment.objects.filter(makerspace=makerspace).exists()


def test_approving_into_a_priced_plan_opens_a_term_but_charges_nothing_yet():
    # The renewal charge near the term's end is the only charge per term (decision D3).
    makerspace = space("actors-approve-plan", enabled_features=_features(TRACKING))
    boss = manager(makerspace, "actors-approve-plan-manager")
    joiner = user("actors-approve-plan-joiner")
    join = membership_services.request_membership(joiner, makerspace)
    plan = MembershipPlan.objects.create(
        makerspace=makerspace, name="Monthly", interval="monthly", amount=Decimal("10"),
    )

    assert _approve(boss, join.id, member_role(makerspace), plan_id=plan.pk).status_code == 200

    term = MembershipTerm.objects.get(membership__user=joiner)
    assert term.status == MembershipTerm.Status.ACTIVE
    assert not Payment.objects.filter(makerspace=makerspace).exists()


def test_dues_and_a_plan_together_raise_two_independent_charges():
    makerspace = space(
        "actors-dues-and-plan", membership_dues_amount=Decimal("25.00"),
        enabled_features=_features(TRACKING),
    )
    boss = manager(makerspace, "actors-dues-and-plan-manager")
    joiner = user("actors-dues-and-plan-joiner")
    join = membership_services.request_membership(joiner, makerspace)
    plan = MembershipPlan.objects.create(
        makerspace=makerspace, name="Monthly", interval="monthly", amount=Decimal("10"),
    )
    assert _approve(boss, join.id, member_role(makerspace), plan_id=plan.pk).status_code == 200
    MembershipTerm.objects.filter(membership__user=joiner).update(ends_at=timezone.now() + timedelta(days=3))

    counts = run_membership_renewals()

    assert counts["charged"] == 1
    subjects = sorted(Payment.objects.filter(makerspace=makerspace).values_list("subject_type", "amount"))
    assert subjects == [
        (Payment.SubjectType.MAKERSPACE_MEMBERSHIP, Decimal("25.00")),
        (Payment.SubjectType.MEMBERSHIP_TERM, Decimal("10.00")),
    ]
    # Idempotent: a second sweep raises nothing more.
    assert run_membership_renewals()["charged"] == 0


def test_a_free_plan_never_charges_and_a_revoked_membership_is_not_swept():
    makerspace = space("actors-free-plan", enabled_features=_features(TRACKING))
    boss = manager(makerspace, "actors-free-plan-manager")
    free_member, revoked_member = (
        MakerspaceMembership.objects.create(
            makerspace=makerspace, user=user(f"actors-free-plan-{name}"),
            assigned_role=member_role(makerspace), role="custom",
        )
        for name in ("free", "revoked")
    )
    free = MembershipPlan.objects.create(makerspace=makerspace, name="Free", interval="monthly", amount=Decimal("0"))
    priced = MembershipPlan.objects.create(makerspace=makerspace, name="Paid", interval="monthly", amount=Decimal("9"))
    soon = timezone.now() + timedelta(days=2)
    MembershipTerm.objects.create(membership=free_member, plan=free, starts_at=soon - timedelta(days=30), ends_at=soon)
    MembershipTerm.objects.create(membership=revoked_member, plan=priced, starts_at=soon - timedelta(days=30), ends_at=soon)
    MakerspaceMembership.objects.filter(pk=revoked_member.pk).update(status="revoked")
    assert boss  # the space has staff; nothing here needs them

    counts = run_membership_renewals()

    assert counts["charged"] == 0
    assert not Payment.objects.filter(makerspace=makerspace).exists()
    free_member.refresh_from_db()
    assert free_member.status == "active"


def test_term_expiry_never_changes_the_membership_status():
    makerspace = space("actors-expiry")
    membership = MakerspaceMembership.objects.create(
        makerspace=makerspace, user=user("actors-expiry-member"),
        assigned_role=member_role(makerspace), role="custom",
    )
    plan = MembershipPlan.objects.create(makerspace=makerspace, name="Monthly", interval="monthly", amount=Decimal("5"))
    past = timezone.now() - timedelta(days=1)
    term = MembershipTerm.objects.create(membership=membership, plan=plan, starts_at=past - timedelta(days=30), ends_at=past)

    assert run_membership_renewals()["expired"] == 1

    term.refresh_from_db()
    membership.refresh_from_db()
    assert term.status == MembershipTerm.Status.EXPIRED
    assert membership.status == "active"
    membership.user.refresh_from_db()
    assert membership.user.access_status == "active"


# ------------------------------------------------------------ M23–M26: who may decide


def test_front_desk_staff_cannot_see_or_decide_membership():
    makerspace = space("actors-front-desk")
    desk = make_handout_member("actors-front-desk-staff", makerspace)
    join = membership_services.request_membership(user("actors-front-desk-joiner"), makerspace)
    client = _client(desk)

    assert client.get(reverse("admin-memberships-roster"), {"makerspace_id": makerspace.pk}).status_code == 404
    assert client.get(reverse("admin-membership-requests"), {"makerspace_id": makerspace.pk}).status_code == 404
    assert _approve(desk, join.id, member_role(makerspace)).status_code == 404
    assert MembershipRequest.objects.get(pk=join.id).state == MembershipRequest.State.REQUESTED


def test_a_space_manager_cannot_invite_someone_into_a_managing_role():
    makerspace = space("actors-escalation")
    boss = manager(makerspace, "actors-escalation-manager")
    managing = MakerspaceRole.objects.get(makerspace=makerspace, slug="space_manager")

    response = _client(boss).post(
        reverse("admin-membership-invitations", args=[makerspace.pk]),
        {"invite_email": "climber@example.test", "role_id": managing.pk}, format="json",
    )

    assert response.status_code == 403
    assert not MembershipRequest.objects.filter(makerspace=makerspace).exists()


def test_a_duplicate_invitation_is_refused():
    makerspace = space("actors-duplicate-invite")
    boss = manager(makerspace, "actors-duplicate-invite-manager")
    url = reverse("admin-membership-invitations", args=[makerspace.pk])
    body = {"invite_email": "twice@example.test", "role_id": member_role(makerspace).pk}

    assert _client(boss).post(url, body, format="json").status_code == 201
    assert _client(boss).post(url, body, format="json").status_code == 400


def test_an_organization_conferred_manager_can_approve_a_join_request():
    makerspace = space("actors-org")
    organization = Organization.objects.create(name="Actors Org", slug="actors-org")
    OrganizationMakerspace.objects.create(
        organization=organization, makerspace=makerspace,
        relationship=OrganizationMakerspace.Relationship.MANAGER,
    )
    org_admin = user("actors-org-admin")
    OrganizationMembership.objects.create(
        organization=organization, user=org_admin, granted_actions=[rbac.Action.MANAGE_MAKERSPACE],
    )
    joiner = user("actors-org-joiner")
    join = membership_services.request_membership(joiner, makerspace)

    response = _approve(org_admin, join.id, member_role(makerspace))

    assert response.status_code == 200, response.data
    assert MakerspaceMembership.objects.get(makerspace=makerspace, user=joiner).status == "active"
    # Authority, never identity: the organization admin did not become a member.
    assert not MakerspaceMembership.objects.filter(makerspace=makerspace, user=org_admin).exists()


# ------------------------------------------------------------- lifecycle rows untested


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
