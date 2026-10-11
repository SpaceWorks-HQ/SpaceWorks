"""Regression coverage for delegated authority boundaries found during F6 review."""
import pytest
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.makerspaces.models import MakerspaceMembership, MakerspaceRole, MembershipPlan, MembershipRequest
from tests.rbac_f6_helpers import community_member, custom_actor
from tests.return_helpers import authenticated_client, make_space, make_user

pytestmark = pytest.mark.django_db


def test_coordinator_cannot_downgrade_or_cancel_a_staff_invitation():
    space = make_space("f6-staff-invitation")
    actor = custom_actor(space, ["manage_members"])
    user = make_user("f6-invited-staff", access_status="active")
    staff_role = MakerspaceRole.objects.get(makerspace=space, slug="inventory_manager")
    member_role = MakerspaceRole.objects.get(makerspace=space, slug="member")
    invitation = MembershipRequest.objects.create(
        makerspace=space, user=user, invite_email=user.email,
        kind="invite", state="invited", assigned_role=staff_role,
    )
    client = authenticated_client(actor)
    base = f"/api/v1/admin/membership-requests/{invitation.pk}"
    assert client.post(f"{base}/approve", {"role_id": member_role.pk}, format="json").status_code == 403
    assert client.post(f"{base}/revoke", {}, format="json").status_code == 403
    invitation.refresh_from_db()
    assert invitation.state == "invited"
    assert invitation.assigned_role_id == staff_role.pk
    assert not MakerspaceMembership.objects.filter(makerspace=space, user=user).exists()
    assert not AuditLog.objects.filter(actor=actor, makerspace=space).exists()


@pytest.mark.parametrize("method", ["post", "patch"])
def test_plan_definition_authority_is_independent_of_roster_grants(method):
    space = make_space(f"f6-plan-definition-{method}")
    actor = custom_actor(space, ["manage_makerspace"])
    client = authenticated_client(actor)
    if method == "post":
        path = f"/api/v1/admin/makerspaces/{space.pk}/membership-plans"
        body = {"name": "Monthly", "interval": "monthly", "amount": "20.00", "currency": "usd"}
    else:
        plan = MembershipPlan.objects.create(makerspace=space, name="Monthly", interval="monthly", amount="10.00", currency="usd")
        path = f"/api/v1/admin/membership-plans/{plan.pk}"
        body = {"amount": "20.00"}
    response = getattr(client, method)(path, body, format="json")
    assert response.status_code == (201 if method == "post" else 200), response.data
    plan = MembershipPlan.objects.get(makerspace=space, name="Monthly")
    assert plan.amount == 20
    assert AuditLog.objects.filter(
        actor=actor, makerspace=space,
        action=f"membership_plan.{'created' if method == 'post' else 'updated'}",
        target_id=str(plan.pk),
    ).exists()


@pytest.mark.parametrize("method", ["post", "patch"])
def test_plan_definition_and_audit_roll_back_together(method, monkeypatch):
    space = make_space(f"f6-plan-audit-{method}")
    actor = custom_actor(space, ["manage_makerspace"])
    if method == "post":
        path = f"/api/v1/admin/makerspaces/{space.pk}/membership-plans"
        body = {"name": "Monthly", "interval": "monthly", "amount": "20.00", "currency": "usd"}
    else:
        plan = MembershipPlan.objects.create(makerspace=space, name="Monthly", interval="monthly", amount="10.00", currency="usd")
        path = f"/api/v1/admin/membership-plans/{plan.pk}"
        body = {"amount": "20.00"}

    def fail_audit(*args, **kwargs):
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr("apps.admin_api.views_membership_plans.audit.record", fail_audit)
    with pytest.raises(RuntimeError, match="audit unavailable"):
        getattr(authenticated_client(actor), method)(path, body, format="json")
    if method == "post":
        assert not MembershipPlan.objects.filter(makerspace=space, name="Monthly").exists()
    else:
        plan.refresh_from_db()
        assert plan.amount == 10


def test_coordinator_can_verify_staff_without_changing_their_role():
    space = make_space("f6-staff-verification")
    actor = custom_actor(space, ["manage_members"])
    staff = custom_actor(space, ["edit_inventory"], name="inventory-staff")
    membership = MakerspaceMembership.objects.get(makerspace=space, user=staff)
    original_role = membership.assigned_role_id
    response = authenticated_client(actor).post(
        f"/api/v1/admin/memberships/{membership.pk}/verify", {}, format="json",
    )
    assert response.status_code == 200
    membership.refresh_from_db()
    assert membership.verified_at is not None
    assert membership.assigned_role_id == original_role
    assert AuditLog.objects.filter(actor=actor, action="membership.verified", target_id=str(membership.pk)).exists()


def test_presence_roster_only_lists_the_authorized_space():
    from datetime import timedelta
    from apps.presence.models import PresenceSession

    space = make_space("f6-presence-local")
    other = make_space("f6-presence-foreign")
    actor = custom_actor(space, ["manage_members"])
    for tenant in (space, other):
        member = community_member(tenant)
        PresenceSession.objects.create(
            makerspace=tenant, membership=member, member=member.user,
            started_at=timezone.now(),
            expires_at=timezone.now() + timedelta(hours=1),
        )
    client = authenticated_client(actor)
    response = client.get(f"/api/v1/admin/makerspace/{space.pk}/presence-sessions/current")
    assert response.status_code == 200
    assert len(response.data) == 1
    assert client.get(f"/api/v1/admin/makerspace/{other.pk}/presence-sessions/current").status_code == 404


@pytest.mark.parametrize("operation", ["verify", "unverify"])
def test_hidden_superadmin_cannot_use_a_delegated_verifier_membership(operation):
    space = make_space(f"f6-hidden-verifier-{operation}")
    space.superadmin_access_enabled = False
    space.save(update_fields=["superadmin_access_enabled", "updated_at"])
    member = community_member(space)
    actor = make_user("f6-hidden-delegate", role="superadmin", access_status="active")
    MakerspaceMembership.objects.create(
        makerspace=space, user=actor, role="custom", can_verify=True,
        assigned_role=member.assigned_role,
    )
    response = authenticated_client(actor).post(
        f"/api/v1/admin/memberships/{member.pk}/{operation}", {}, format="json",
    )
    assert response.status_code == 404
    from rest_framework.exceptions import PermissionDenied
    from apps.makerspaces import membership_services

    service = membership_services.verify_member if operation == "verify" else membership_services.unverify_member
    with pytest.raises(PermissionDenied):
        service(actor, member)
    member.refresh_from_db()
    assert member.verified_at is None
    assert not AuditLog.objects.filter(actor=actor, makerspace=space).exists()


@pytest.mark.parametrize("operation", ["verify", "unverify", "refer", "verifier"])
def test_verification_services_recheck_the_locked_module_gate(operation):
    from rest_framework.exceptions import ValidationError
    from apps.makerspaces import membership_services
    from tests.module_helpers import disable_module

    space = make_space(f"f6-verification-off-{operation}")
    member = community_member(space)
    actor = custom_actor(space, ["manage_members"])
    MakerspaceMembership.objects.filter(pk=member.pk).update(can_refer=False, can_verify=False)
    disable_module(space, "membership")
    operations = {
        "verify": lambda: membership_services.verify_member(actor, member),
        "unverify": lambda: membership_services.unverify_member(actor, member),
        "refer": lambda: membership_services.set_can_refer(actor, member, True),
        "verifier": lambda: membership_services.set_can_verify(actor, member, True),
    }
    with pytest.raises(ValidationError):
        operations[operation]()
    member.refresh_from_db()
    assert member.verified_at is None
    assert not member.can_refer and not member.can_verify
    assert not AuditLog.objects.filter(actor=actor, makerspace=space).exists()
