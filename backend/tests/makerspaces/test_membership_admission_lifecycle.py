"""Returning members, account-less desk applications and private lifecycle notices."""
from decimal import Decimal
from unittest.mock import Mock

import pytest

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.makerspaces import membership_services
from apps.makerspaces.membership_admission_notifications import notify_admission
from apps.makerspaces.membership_admission_settings import update_settings
from apps.makerspaces.models import MakerspaceMembership, MembershipRequest
from apps.makerspaces.walk_in_services import create_walk_in_member
from apps.payments.models import Payment
from apps.payments.reconciliation import mark_offline
from tests.makerspaces.test_membership_admission_matrix import _setup
from tests.makerspaces.test_membership_admission_api import QUESTION, client
from tests.makerspaces.test_membership_j1 import member_role, user
from tests.module_helpers import disable_module
from tests.return_helpers import settlement_details

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.mark.parametrize("rule", ["once", "each_join"])
@pytest.mark.parametrize("timing", ["before_activation", "after_activation"])
def test_rejoin_dues_rule_records_a_fresh_subject_without_double_charging(rule, timing):
    space, actor, applicant, plan, _ = _setup("open", timing=timing, joining_fee=Decimal("5.00"), rejoin_dues_rule=rule)
    membership_services.request_membership(applicant, space)
    original = MembershipRequest.objects.get(makerspace=space, user=applicant)
    payment = Payment.objects.get(pk=original.admission_payment_id)
    mark_offline(payment, actor, settlement=settlement_details())
    member = MakerspaceMembership.objects.get(makerspace=space, user=applicant)
    membership_services.revoke_membership(actor, member)
    second = membership_services.request_membership(applicant, space)
    returning = MembershipRequest.objects.filter(makerspace=space, user=applicant).first()
    assert returning.pk != original.pk and returning.rejoining
    if rule == "once":
        assert second["outcome"] == "joined" and returning.admission_payment_id is None
        assert Payment.objects.filter(makerspace=space).count() == 1
    else:
        charge = Payment.objects.get(pk=returning.admission_payment_id)
        assert charge.subject_id == returning.pk and charge.amount == Decimal("5.00")
        if timing == "before_activation":
            assert second["state"] == "awaiting_payment"
            own = client(applicant).get(f"/api/v1/member/makerspaces/{space.pk}/admission")
            assert own.status_code == 200 and own.data["id"] == returning.pk
        mark_offline(charge, actor, settlement=settlement_details())
        assert Payment.objects.filter(makerspace=space).count() == 2
    member.refresh_from_db()
    assert member.status == "active"
    assert member.terms.count() == 2


def test_walk_in_paid_before_activation_waits_for_offline_receipt():
    space, actor, _, plan, _ = _setup("open", True, "before_activation")
    row = create_walk_in_member(actor, space, display_name="Desk applicant")
    assert isinstance(row, MembershipRequest) and row.state == "awaiting_payment"
    assert row.user.is_walk_in and not row.user.has_usable_password()
    assert not MakerspaceMembership.objects.filter(user=row.user, makerspace=space).exists()
    mark_offline(row.admission_payment, actor, settlement=settlement_details())
    row.refresh_from_db()
    assert row.state == "active"
    member = MakerspaceMembership.objects.get(user=row.user, makerspace=space)
    assert member.terms.get().plan_id == plan.pk and not member.can_refer


def test_walk_in_answers_and_approval_do_not_give_front_desk_decision_authority():
    space, actor, _, _, _ = _setup("approval", application_schema=QUESTION)
    # Use a custom role rather than editing the protected Member role.
    from apps.makerspaces.models import MakerspaceRole
    front_role = MakerspaceRole.objects.create(makerspace=space, name="Desk", slug="desk", granted_actions=["issue_direct_loan"])
    desk = user("walk-in-desk")
    MakerspaceMembership.objects.create(makerspace=space, user=desk, assigned_role=front_role)
    row = create_walk_in_member(desk, space, display_name="Approval applicant", application_answers={"why": "Learn safely"})
    assert row.state == "requested" and row.approved_at is None
    assert not MakerspaceMembership.objects.filter(makerspace=space, user=row.user).exists()
    membership_services.approve_request(actor, row, member_role(space))
    row.refresh_from_db()
    assert row.state == "active"


def test_walk_in_http_pending_shape_and_closed_refusal_roll_back_person_creation():
    space, actor, _, _, _ = _setup("vouch", application_schema=QUESTION)
    url = f"/api/v1/admin/makerspaces/{space.pk}/walk-in-members"
    schema = client(actor).get(url)
    assert schema.status_code == 200 and schema.data["application_schema"] == QUESTION
    response = client(actor).post(url, {"display_name": "Pending guest", "application_answers": {"why": "Woodworking"}}, format="json")
    assert response.status_code == 201 and response.data["admission_request"]["state"] == "awaiting_vouches"
    update_settings(actor, space, {"join_mode": "closed"})
    count = User.objects.count()
    refused = client(actor).post(url, {"display_name": "Refused guest"}, format="json")
    assert refused.status_code == 400 and refused.data["code"] == "membership_closed"
    assert User.objects.count() == count


def test_membership_off_keeps_core_walk_in_and_staff_invitation_behaviour():
    space, actor, _, _, _ = _setup("closed")
    disable_module(space, "membership")
    conditions = client(actor).get(f"/api/v1/admin/makerspaces/{space.pk}/walk-in-members")
    assert conditions.status_code == 200 and conditions.data["join_mode"] == "open"
    assert conditions.data["application_schema"] is None and conditions.data["joining_fee"] == "0.00"
    member = create_walk_in_member(actor, space, display_name="Core identity")
    assert member.status == "active" and member.user.is_walk_in
    from apps.makerspaces.models import MakerspaceRole
    staff_role = MakerspaceRole.objects.get(makerspace=space, slug="inventory_manager")
    invited = user("module-off-staff")
    invitation = membership_services.invite_membership(actor, space, invited.email, staff_role)
    membership_services.claim_invitation(invited, invitation.pk)
    assert membership_services.approve_request(actor, invitation, staff_role).status == "active"


@pytest.mark.parametrize("event", ["awaiting_payment", "payment_due", "declined"])
def test_admission_family_addresses_the_owned_applicant_including_pending_rejoin(event, monkeypatch):
    space, actor, applicant, _, _ = _setup("approval", True, "before_activation")
    # A previous revoked membership does not erase ownership of a new application.
    MakerspaceMembership.objects.create(makerspace=space, user=applicant, assigned_role=member_role(space), status="revoked")
    result = membership_services.request_membership(applicant, space)
    row = MembershipRequest.objects.get(pk=result["request_id"])
    captures = []
    monkeypatch.setattr("apps.integrations.notifications_research.notify_lifecycle", lambda *args, **kw: captures.append(kw))
    notify_admission(row, event)
    assert captures[-1]["feature"] == "members" and captures[-1]["event"] == event
    payload = captures[-1]["build"]()
    own_emails = [email for email in payload.emails if email.audience == "requester"]
    assert [email.to_email for email in own_emails] == [applicant.email]
    assert "application_answers" not in payload.data


def test_outbound_notice_failure_never_rolls_back_awaiting_payment(monkeypatch):
    space, actor, applicant, _, _ = _setup("approval", True, "before_activation")
    outcome = membership_services.request_membership(applicant, space)
    row = MembershipRequest.objects.get(pk=outcome["request_id"])
    monkeypatch.setattr("apps.integrations.notifications_research.notify_lifecycle", Mock(side_effect=RuntimeError("mail unavailable")))
    membership_services.approve_request(actor, row, member_role(space))
    row.refresh_from_db()
    assert row.state == "awaiting_payment" and row.admission_payment.status == "pending"
    assert AuditLog.objects.filter(action="membership.application_approved", target_id=str(row.pk)).exists()


def test_configured_core_creation_keeps_the_existing_space_manager_protection():
    from apps.admin_api.services_staff import attach_staff_membership
    from rest_framework.exceptions import PermissionDenied
    from tests.makerspaces.test_membership_j1 import manager
    space, original, _, _, _ = _setup("open")
    actor = manager(space, "another-admission-manager")
    with pytest.raises(PermissionDenied):
        attach_staff_membership(actor=actor, makerspace=space, username=original.username,
                                role=member_role(space))
    original_membership = MakerspaceMembership.objects.get(user=original, makerspace=space)
    assert original_membership.assigned_role.slug == "space_manager"


def test_core_settings_authority_does_not_replace_the_membership_approval_action():
    from apps.admin_api.services_staff import attach_staff_membership
    from apps.makerspaces.models import MakerspaceRole
    from rest_framework.exceptions import PermissionDenied
    space, _, _, _, _ = _setup("approval")
    role = MakerspaceRole.objects.create(makerspace=space, name="Settings only", slug="settings-only",
                                        granted_actions=["manage_makerspace"])
    actor = user("admission-settings-only")
    MakerspaceMembership.objects.create(makerspace=space, user=actor, assigned_role=role)
    with pytest.raises(PermissionDenied):
        attach_staff_membership(actor=actor, makerspace=space, username="unapproved-core-person",
                                role=member_role(space))
    assert not User.objects.filter(username="unapproved-core-person").exists()
