"""Each roster surface admits delegated member management and retains tenant fences."""
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.accounts import rbac
from apps.audit.models import AuditLog
from apps.makerspaces.models import (
    InvitationRequest, Makerspace, MakerspaceMembership, MakerspaceRole,
    MakerspaceWaiver, MembershipPlan, MembershipRequest, MembershipTerm,
)
from tests.module_helpers import disable_module
from tests.rbac_f6_helpers import community_member, custom_actor
from tests.return_helpers import authenticated_client, make_member, make_space, make_user

pytestmark = pytest.mark.django_db
CASES = [
    "roster", "legacy-roster", "requests", "roles", "presence", "invite", "approve",
    "decline", "revoke", "role", "capabilities", "verify", "unverify", "witness",
    "plans", "terms", "open-term", "cancel-term", "invitation-requests",
    "invite-request", "decline-request", "cards", "issue-card",
]


def surface(case, space):
    membership = community_member(space)
    member_role = membership.assigned_role
    joiner = make_user(f"{space.slug}-joiner", access_status="active")
    joiner.email_verified_at = timezone.now()
    joiner.save(update_fields=["email_verified_at"])
    request = MembershipRequest.objects.create(
        makerspace=space, user=joiner, invite_email=joiner.email, requested_by=joiner,
        kind="request", state="requested",
    )
    lead = InvitationRequest.objects.create(makerspace=space, name="Applicant", email="applicant@example.com")
    plan = MembershipPlan.objects.create(makerspace=space, name="Free", interval="monthly", amount="0", currency="usd")
    term = MembershipTerm.objects.create(
        membership=membership, plan=plan, starts_at=timezone.now(),
        ends_at=timezone.now() + timedelta(days=30),
    )
    MakerspaceWaiver.objects.create(makerspace=space, body="Terms", version="v1", is_active=True)
    routes = {
        "roster": ("get", f"memberships?makerspace_id={space.pk}", None),
        "legacy-roster": ("get", f"makerspaces/{space.pk}/memberships", None),
        "requests": ("get", f"membership-requests?makerspace_id={space.pk}", None),
        "roles": ("get", f"makerspaces/{space.pk}/roles", None),
        "presence": ("get", f"makerspace/{space.pk}/presence-sessions/current", None),
        "invite": ("post", f"makerspace/{space.pk}/membership-invitations", {"invite_email": "new@example.com", "role_id": member_role.pk}),
        "approve": ("post", f"membership-requests/{request.pk}/approve", {"role_id": member_role.pk, "plan_id": plan.pk}),
        "decline": ("post", f"membership-requests/{request.pk}/revoke", {}),
        "revoke": ("post", f"memberships/{membership.pk}/revoke", {}),
        "role": ("patch", f"memberships/{membership.pk}/role", {"role_id": member_role.pk}),
        "capabilities": ("patch", f"memberships/{membership.pk}/capabilities", {"can_refer": True, "can_verify": True}),
        "verify": ("post", f"memberships/{membership.pk}/verify", {}),
        "unverify": ("post", f"memberships/{membership.pk}/unverify", {}),
        "witness": ("post", f"memberships/{membership.pk}/waiver/witness", {}),
        "plans": ("get", f"makerspaces/{space.pk}/membership-plans", None),
        "terms": ("get", f"memberships/{membership.pk}/terms", None),
        "open-term": ("post", f"memberships/{membership.pk}/terms", {"plan_id": plan.pk}),
        "cancel-term": ("post", f"membership-terms/{term.pk}/cancel", {}),
        "invitation-requests": ("get", f"makerspaces/{space.pk}/invitation-requests", None),
        "invite-request": ("post", f"invitation-requests/{lead.pk}/invite", {"role_id": member_role.pk}),
        "decline-request": ("post", f"invitation-requests/{lead.pk}/decline", {}),
        "cards": ("get", f"makerspaces/{space.pk}/member-cards", None),
        "issue-card": ("post", f"makerspaces/{space.pk}/member-cards/{membership.pk}/issue", {}),
    }
    return routes[case]


def call(actor, route):
    method, path, body = route
    return getattr(authenticated_client(actor), method)(f"/api/v1/admin/{path}", body, format="json")


@pytest.mark.parametrize("case", CASES)
@pytest.mark.parametrize("authority", ["narrow", "missing", "foreign", "inventory", "hidden-superadmin"])
def test_member_endpoint_matrix(case, authority):
    space = make_space("f6-member-matrix")
    route = surface(case, space)
    if authority == "hidden-superadmin":
        Makerspace.objects.filter(pk=space.pk).update(superadmin_access_enabled=False)
        actor = make_user("f6-hidden-superadmin", role="superadmin", access_status="active")
    elif authority == "inventory":
        actor = make_member("f6-inventory", space, membership_role="inventory_manager", role="requester")
    else:
        actor_space = make_space("f6-other") if authority == "foreign" else space
        actions = [] if authority == "missing" else [rbac.Action.MANAGE_MEMBERS]
        actor = custom_actor(actor_space, actions)
    response = call(actor, route)
    if authority == "narrow" or (authority == "inventory" and case == "witness"):
        assert response.status_code in (200, 201), response.data
        if route[0] != "get":
            assert AuditLog.objects.filter(actor=actor, makerspace=space).exists()
        if case == "roles":
            assert all(not row["granted_actions"] for row in response.data)
    else:
        assert response.status_code in (403, 404), response.data
        assert not AuditLog.objects.filter(actor=actor, makerspace=space).exists()


@pytest.mark.parametrize("case", ["plans", "verify", "capabilities", "issue-card", "invitation-requests"])
def test_member_module_off_is_400(case):
    space = make_space("f6-member-off")
    route = surface(case, space)
    actor = custom_actor(space, [rbac.Action.MANAGE_MEMBERS])
    disable_module(space, "membership")
    assert call(actor, route).status_code == 400


def test_coordinator_cannot_manage_staff_settings_plan_prices_or_waiver_text():
    space = make_space("f6-member-boundary")
    actor = custom_actor(space, [rbac.Action.MANAGE_MEMBERS])
    manager = make_member("f6-protected-manager", space)
    manager_membership = MakerspaceMembership.objects.get(user=manager, makerspace=space)
    member_role = MakerspaceRole.objects.get(makerspace=space, slug="member")
    staff_role = MakerspaceRole.objects.get(makerspace=space, slug="inventory_manager")
    member = community_member(space)
    client = authenticated_client(actor)
    base = "/api/v1/admin"
    assert client.post(f"{base}/memberships/{manager_membership.pk}/revoke", {}, format="json").status_code == 403
    assert client.patch(f"{base}/memberships/{manager_membership.pk}/role", {"role_id": member_role.pk}, format="json").status_code == 403
    assert client.patch(f"{base}/memberships/{member.pk}/role", {"role_id": staff_role.pk}, format="json").status_code == 403
    assert client.post(f"{base}/makerspace/{space.pk}/membership-invitations", {"invite_email": "staff@example.com", "role_id": staff_role.pk}, format="json").status_code == 403
    assert client.post(f"{base}/makerspaces/{space.pk}/roles", {"name": "Escalation", "granted_actions": []}, format="json").status_code in (403, 404)
    assert client.post(f"{base}/makerspaces/{space.pk}/membership-plans", {"name": "Paid", "interval": "monthly", "amount": "20", "currency": "usd"}, format="json").status_code in (403, 404)
    assert client.put(f"{base}/makerspaces/{space.pk}/waiver", {"body": "Changed", "version": "v2"}, format="json").status_code in (403, 404)
    manager_membership.refresh_from_db()
    assert manager_membership.status == "active"


def test_roster_does_not_disclose_money_to_members_only_role():
    from tests.rbac_f6_helpers import charge
    space = make_space("f6-roster-money")
    member = community_member(space)
    charge(space, member)
    actor = custom_actor(space, [rbac.Action.MANAGE_MEMBERS])
    response = authenticated_client(actor).get(f"/api/v1/admin/memberships?makerspace_id={space.pk}")
    row = next(row for row in response.data["results"] if row["id"] == member.pk)
    assert row["payment"] is None
