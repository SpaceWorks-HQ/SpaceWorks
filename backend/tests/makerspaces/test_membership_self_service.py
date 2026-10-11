"""Cancel stops future renewal; leave reuses every revocation cleanup seam."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.audit.models import AuditLog
from apps.makerspaces.membership_plan_services import create_term
from apps.makerspaces.models import MakerspaceMembership, MakerspaceRole, MembershipPlan
from apps.payments.models import Payment
from apps.payments.services import create_payment
from tests.return_helpers import make_space, make_user

pytestmark = pytest.mark.django_db


@pytest.fixture
def member_account():
    space = make_space("self-service-member")
    space.enabled_modules = sorted(set(space.enabled_modules) | {"membership", "member_accounts"})
    space.enabled_features = sorted(set(space.enabled_features) | {"membership.self_service"})
    space.save()
    user = make_user("voluntary-member", access_status="active")
    role = MakerspaceRole.objects.get(makerspace=space, slug="member")
    membership = MakerspaceMembership.objects.create(makerspace=space, user=user,
                                                    assigned_role=role, role="custom")
    client = APIClient()
    client.force_authenticate(user)
    return user, space, membership, client


def route(space, action):
    return f"/api/v1/member/makerspaces/{space.pk}/account/{action}"


def test_cancel_is_audited_idempotent_and_keeps_current_term(member_account):
    user, space, membership, client = member_account
    plan = MembershipPlan.objects.create(makerspace=space, name="Monthly",
                                         interval="monthly", amount=Decimal("10"), currency="usd")
    term = create_term(user, membership, plan, starts_at=timezone.now() - timedelta(days=20))
    payment = create_payment(makerspace=space, member=user, amount=plan.amount,
        currency="usd", subject_type=Payment.SubjectType.MEMBERSHIP_TERM,
        subject_id=term.pk, created_by=user, subject_label="Renewal")
    term.renewal_payment = payment
    term.save(update_fields=["renewal_payment"])
    for _ in range(2):
        response = client.post(route(space, "cancel"), {"reason": "Moving away"}, format="json")
        assert response.status_code == 200
        assert response.data["renewal_cancelled_at"] is not None
    membership.refresh_from_db()
    term.refresh_from_db()
    payment.refresh_from_db()
    assert membership.status == "active" and membership.renewal_cancelled_at is not None
    assert term.status == "active" and payment.status == "canceled"
    assert AuditLog.objects.filter(action="membership.renewal_cancelled", actor=user).count() == 1
    assert AuditLog.objects.get(action="membership.renewal_cancelled", actor=user).meta["reason"] == "Moving away"


def test_cancel_requires_reason(member_account):
    _, space, _, client = member_account
    assert client.post(route(space, "cancel"), {}, format="json").status_code == 400
    assert client.post(route(space, "cancel"), {"reason": "   "}, format="json").status_code == 400


def test_leave_preserves_account_and_history_and_does_not_flag_vouchers(member_account, monkeypatch):
    user, space, membership, client = member_account
    plan = MembershipPlan.objects.create(makerspace=space, name="Free", interval="monthly")
    term = create_term(user, membership, plan)
    calls = []
    monkeypatch.setattr("apps.makerspaces.membership_vouching.flag_vouchers", lambda *args: calls.append(args))
    response = client.post(route(space, "leave"), {"reason": "I have moved"}, format="json")
    assert response.status_code == 200 and response.data["status"] == "revoked"
    membership.refresh_from_db()
    user.refresh_from_db()
    term.refresh_from_db()
    assert membership.status == "revoked" and not membership.can_refer and not membership.can_verify
    assert user.is_active and user.access_status == "active"
    assert term.status == "cancelled" and calls == []
    event = AuditLog.objects.get(action="membership.left", actor=user)
    assert event.meta["reason"] == "I have moved"
    assert client.get(route(space, "membership")).status_code == 404


def test_fresh_admission_clears_previous_lifecycles_renewal_cancellation(member_account):
    from apps.makerspaces.membership_activation import _activate_membership

    user, space, membership, client = member_account
    assert client.post(route(space, "leave"), {"reason": "Leaving for a season"}, format="json").status_code == 200
    membership.refresh_from_db()
    assert membership.renewal_cancelled_at is not None
    role = MakerspaceRole.objects.get(makerspace=space, slug="member")
    renewed = _activate_membership(user, space, user, role, source="open", skip_dues=True)
    assert renewed.pk == membership.pk and renewed.status == "active"
    assert renewed.renewal_cancelled_at is None
    assert AuditLog.objects.filter(action="membership.joined", target_id=str(renewed.pk)).exists()


def test_sole_manager_cannot_leave_and_another_manager_allows_it(member_account):
    _, space, membership, client = member_account
    manager = MakerspaceRole.objects.get(makerspace=space, slug="space_manager")
    membership.assigned_role = manager
    membership.save(update_fields=["assigned_role"])
    assert client.post(route(space, "leave"), {"reason": "Leaving"}, format="json").status_code == 403
    membership.refresh_from_db()
    assert membership.status == "active"
    second = make_user("remaining-manager", access_status="active")
    MakerspaceMembership.objects.create(makerspace=space, user=second, assigned_role=manager)
    second.is_active = False
    second.save(update_fields=["is_active"])
    assert client.post(route(space, "leave"), {"reason": "Leaving"}, format="json").status_code == 403
    second.is_active = True
    second.save(update_fields=["is_active"])
    assert client.post(route(space, "leave"), {"reason": "Leaving"}, format="json").status_code == 200


def test_cancel_cannot_mutate_foreign_tenant(member_account):
    _, _, membership, client = member_account
    foreign = make_space("foreign-cancel")
    assert client.post(route(foreign, "cancel"), {"reason": "Leaving"}, format="json").status_code == 404
    membership.refresh_from_db()
    assert membership.renewal_cancelled_at is None


@pytest.mark.parametrize("action", ["cancel", "leave"])
def test_membership_off_answers_400(member_account, action):
    _, space, membership, client = member_account
    space.enabled_modules = [value for value in space.enabled_modules if value != "membership"]
    space.save(update_fields=["enabled_modules"])
    assert client.post(route(space, action), {"reason": "Leaving"}, format="json").status_code == 400
    membership.refresh_from_db()
    assert membership.status == "active" and membership.renewal_cancelled_at is None
