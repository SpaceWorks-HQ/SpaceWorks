"""Every remaining module-off HTTP row from the membership audit (A7)."""
from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.makerspaces import member_card_services
from apps.makerspaces.models import InvitationRequest, MakerspaceMembership, MembershipPlan, MembershipTerm
from tests.makerspaces.test_membership_j1 import manager, member_role, space, user
from tests.module_helpers import disable_module
from tests.return_helpers import authenticated_client

pytestmark = pytest.mark.django_db


@pytest.fixture
def state():
    makerspace = space("offstate-membership", referrals_enabled=True)
    boss = manager(makerspace, "offstate-membership-manager")
    row = MakerspaceMembership.objects.create(
        makerspace=makerspace, user=user("offstate-membership-member"),
        assigned_role=member_role(makerspace), role="custom",
    )
    card = member_card_services.issue_card(boss, row)
    plan = MembershipPlan.objects.create(makerspace=makerspace, name="Monthly", interval="monthly", amount="10")
    now = timezone.now()
    term = MembershipTerm.objects.create(membership=row, plan=plan, starts_at=now, ends_at=now + timedelta(days=30))
    invitation = InvitationRequest.objects.create(makerspace=makerspace, name="Visitor", email="visitor@example.test")
    disable_module(makerspace, "membership")
    return makerspace, boss, row, card, plan, term, invitation


@pytest.mark.parametrize("route,method,target,body", [
    ("admin-membership-plans", "get", "space", None),
    ("admin-membership-plans", "post", "space", {"name": "New", "interval": "monthly", "amount": "0", "currency": "usd"}),
    ("admin-membership-plan-detail", "patch", "plan", {"name": "Renamed"}),
    ("admin-membership-terms", "get", "member", None),
    ("admin-membership-terms", "post", "member", {"plan_id": "plan"}),
    ("admin-membership-term-cancel", "post", "term", {}),
    ("admin-invitation-requests", "get", "space", None),
    ("admin-invitation-request-invite", "post", "invitation", {"role_id": "role"}),
    ("admin-invitation-request-decline", "post", "invitation", {}),
    ("admin-member-cards", "get", "space", None),
    ("admin-member-cards-sheet", "post", "space", {}),
    ("admin-member-card-resolve", "post", "space", {"payload": "payload"}),
    ("admin-member-card-template", "get", "space", None),
    ("admin-member-card-template", "put", "space", {}),
    ("admin-member-card-reissue", "post", "card", {"reason": "lost"}),
    ("admin-member-card-revoke", "post", "card", {"reason": "lost"}),
    ("admin-member-card-print", "post", "card", {}),
])
def test_staff_community_routes_refuse_module_off_with_400(state, route, method, target, body):
    makerspace, boss, row, card, plan, term, invitation = state
    ids = {"space": makerspace.pk, "member": row.pk, "card": card.pk, "plan": plan.pk, "term": term.pk, "invitation": invitation.pk}
    values = {"plan": plan.pk, "role": member_role(makerspace).pk, "payload": member_card_services.active_qr(card).payload}
    payload = {key: values.get(value, value) for key, value in (body or {}).items()}
    response = getattr(authenticated_client(boss), method)(reverse(route, args=[ids[target]]), payload, format="json")
    assert response.status_code == 400, response.data
    assert "membership" in str(response.data)
    card.refresh_from_db(); term.refresh_from_db(); invitation.refresh_from_db(); plan.refresh_from_db()
    assert card.revoked_at is None and card.print_count == 0
    assert term.status == "active" and invitation.status == "pending" and plan.name == "Monthly"


def test_card_issue_is_gated_even_with_a_valid_member(state):
    makerspace, boss, row, *_ = state
    response = authenticated_client(boss).post(reverse("admin-member-card-issue", args=[makerspace.pk, row.pk]), {}, format="json")
    assert response.status_code == 400 and "membership" in str(response.data)


@pytest.mark.parametrize("route,method,body", [
    ("member-card", "get", {}), ("member-card", "patch", {"printed_name": "Guest"}),
    ("member-card-photo", "post", {"content_type": "image/jpeg"}),
    ("member-card-photo", "put", {"object_key": "unused", "content_type": "image/jpeg", "consent": True}),
    ("member-card-photo", "delete", {}), ("member-card-preview", "get", {}),
    ("member-profile", "get", {}), ("member-profile", "put", {"bio": "New"}),
    ("member-profile-image", "post", {"filename": "face.jpg", "content_type": "image/jpeg"}),
    ("member-profile-image", "put", {"object_key": "unused"}), ("member-profile-image", "delete", {}),
    ("member-directory", "get", {}), ("member-activity", "get", {}),
    ("member-referrals", "post", {"invite_email": "new@example.test"}),
])
def test_member_community_routes_refuse_module_off_with_400(state, route, method, body):
    makerspace, _, row, *_ = state
    response = getattr(authenticated_client(row.user), method)(reverse(route, args=[makerspace.pk]), body, format="json")
    assert response.status_code == 400, response.data
    assert "membership" in str(response.data)


def test_directory_detail_is_gated_before_unknown_target_lookup(state):
    makerspace, _, row, *_ = state
    response = authenticated_client(row.user).get(reverse("member-directory-detail", args=[makerspace.pk, row.pk]))
    assert response.status_code == 400


def test_publish_and_witness_waivers_remain_core_module_off(state):
    makerspace, boss, row, *_ = state
    client = authenticated_client(boss)
    published = client.put(reverse("admin-makerspace-waiver", args=[makerspace.pk]), {"version": "v1", "body": "Handle tools safely"}, format="json")
    assert published.status_code == 200
    witnessed = client.post(reverse("admin-membership-waiver-witness", args=[row.pk]), {}, format="json")
    assert witnessed.status_code == 200
    row.refresh_from_db()
    from apps.makerspaces.models import MakerspaceWaiver
    from apps.makerspaces.waiver_state import current_acceptance
    from apps.audit.models import AuditLog

    assert current_acceptance(
        row, active_waiver=MakerspaceWaiver.objects.get(makerspace=makerspace, is_active=True)
    )
    assert AuditLog.objects.filter(action="makerspace.waiver_published", makerspace=makerspace, actor=boss).exists()
    assert AuditLog.objects.filter(action="membership.waiver_witnessed", makerspace=makerspace, actor=boss).exists()
