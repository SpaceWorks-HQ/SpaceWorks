"""Plan audit entries, fail-safe renewals and settlement/term independence."""
import logging
from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.makerspaces.membership_plan_services import create_term, run_membership_renewals
from apps.makerspaces.models import MakerspaceMembership, MembershipPlan, MembershipTerm
from apps.payments.models import Payment
from tests.makerspaces.test_membership_j1 import manager, member_role, space, user
from tests.makerspaces.test_membership_matrix import TRACKING, _features
from tests.return_helpers import authenticated_client, settlement_payload

pytestmark = pytest.mark.django_db


def setup_term():
    makerspace = space("remaining-plan", enabled_features=_features(TRACKING))
    boss = manager(makerspace, "remaining-plan-boss")
    row = MakerspaceMembership.objects.create(makerspace=makerspace, user=user("remaining-plan-member"), assigned_role=member_role(makerspace), role="custom")
    plan = MembershipPlan.objects.create(makerspace=makerspace, name="Monthly", interval="monthly", amount="10")
    term = create_term(boss, row, plan)
    MembershipTerm.objects.filter(pk=term.pk).update(ends_at=timezone.now() + timedelta(days=2))
    return makerspace, boss, row, plan, term


def test_renewal_failure_is_logged_preserves_term_and_does_not_stop_other_members(monkeypatch, caplog):
    makerspace, boss, row, plan, term = setup_term()
    other = MakerspaceMembership.objects.create(makerspace=makerspace, user=user("remaining-plan-other"), assigned_role=member_role(makerspace), role="custom")
    other_term = create_term(boss, other, plan)
    MembershipTerm.objects.filter(pk=other_term.pk).update(ends_at=timezone.now() + timedelta(days=3))
    from apps.payments import services
    real_create = services.create_payment

    def create(**kwargs):
        if kwargs["subject_id"] == term.pk:
            raise RuntimeError("provider unavailable")
        return real_create(**kwargs)

    monkeypatch.setattr(services, "create_payment", create)
    with caplog.at_level(logging.WARNING):
        counts = run_membership_renewals()
    assert counts["failed"] == counts["charged"] == 1
    term.refresh_from_db(); row.refresh_from_db()
    assert term.status == "active" and term.renewal_payment_id is None and row.status == "active"
    assert "membership_renewal_charge_failed" in caplog.text


def test_settling_a_renewal_does_not_create_a_second_term():
    makerspace, boss, row, _, term = setup_term()
    assert run_membership_renewals()["charged"] == 1
    payment = Payment.objects.get(subject_type="membership_term", subject_id=term.pk)
    response = authenticated_client(boss).post(reverse("payment-reconciliation-mark-offline", args=[makerspace.pk, payment.pk]), settlement_payload(), format="json")
    assert response.status_code == 200
    payment.refresh_from_db()
    assert payment.status == Payment.Status.PAID_OFFLINE
    assert MembershipTerm.objects.filter(membership=row).count() == 1


def test_plan_create_patch_and_term_cancel_record_audits():
    makerspace, boss, row, plan, term = setup_term()
    client = authenticated_client(boss)
    created = client.post(reverse("admin-membership-plans", args=[makerspace.pk]), {"name": "Yearly", "interval": "yearly", "amount": "30", "currency": "usd"}, format="json")
    assert created.status_code == 201
    assert client.patch(reverse("admin-membership-plan-detail", args=[plan.pk]), {"name": "Monthly updated"}, format="json").status_code == 200
    assert client.post(reverse("admin-membership-term-cancel", args=[term.pk])).status_code == 200
    assert AuditLog.objects.filter(action="membership_plan.created", actor=boss, makerspace=makerspace).count() == 1
    assert AuditLog.objects.filter(action="membership_plan.updated", actor=boss, makerspace=makerspace).count() == 1
    assert AuditLog.objects.filter(action="membership.term_cancelled", actor=boss, makerspace=makerspace).count() == 1
