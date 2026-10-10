"""Every admission recipe works with free/paid plans and either charge timing."""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.audit.models import AuditLog
from apps.makerspaces import membership_services
from apps.makerspaces.invitation_request_services import submit_invitation_request
from apps.makerspaces.membership_admission_forms import answers_for
from apps.makerspaces.membership_admission_settings import AdmissionError, update_settings
from apps.makerspaces.membership_vouching import vouch_for_request
from apps.makerspaces.models import (
    MakerspaceMembership, MembershipPlan, MembershipRequest, MembershipTerm,
)
from apps.payments.models import ManualSettlement, Payment
from apps.payments.reconciliation import mark_offline
from tests.makerspaces.test_membership_j1 import manager, member_role, space, user
from tests.return_helpers import settlement_details

pytestmark = pytest.mark.django_db(transaction=True)


def _setup(mode="approval", paid=False, timing="after_activation", **overrides):
    makerspace = space("admission-matrix")
    makerspace.enabled_modules = sorted(set(makerspace.enabled_modules or []) | {"membership"})
    makerspace.enabled_features = sorted(set(makerspace.enabled_features or []) | {
        "charges.enabled", "charges.membership",
    })
    makerspace.save(update_fields=["enabled_modules", "enabled_features"])
    actor = manager(makerspace)
    applicant = user("matrix-applicant")
    plan = MembershipPlan.objects.create(
        makerspace=makerspace, name="Default admission plan", interval="monthly",
        amount=Decimal("20.00") if paid else Decimal("0.00"), currency="usd",
    )
    values = {"join_mode": mode, "payment_timing": timing, "default_plan": plan}
    values.update(overrides)
    policy = update_settings(actor, makerspace, values)
    makerspace.refresh_from_db()
    return makerspace, actor, applicant, plan, policy


def _voucher(makerspace, name="matrix-voucher", days=45):
    actor = user(name)
    membership = MakerspaceMembership.objects.create(
        makerspace=makerspace, user=actor, assigned_role=member_role(makerspace),
        role="custom", status="active", activated_at=timezone.now() - timedelta(days=days),
    )
    return actor, membership


def _application(makerspace, applicant, answers=None):
    membership_services.request_membership(applicant, makerspace, application_answers=answers)
    return MembershipRequest.objects.get(makerspace=makerspace, user=applicant)


@pytest.mark.parametrize("mode", ["open", "approval", "invite_only", "vouch", "closed"])
@pytest.mark.parametrize("paid", [False, True], ids=["free", "paid"])
@pytest.mark.parametrize("timing", ["before_activation", "after_activation"])
def test_mode_price_and_payment_timing_condition_matrix(mode, paid, timing):
    makerspace, actor, applicant, plan, _ = _setup(mode, paid, timing)
    if mode == "closed":
        with pytest.raises(AdmissionError) as refused:
            membership_services.request_membership(applicant, makerspace)
        assert refused.value.detail["code"] == "membership_closed"
        assert not MembershipRequest.objects.filter(makerspace=makerspace).exists()
        assert not Payment.objects.filter(makerspace=makerspace).exists()
        return
    if mode == "invite_only":
        with pytest.raises(AdmissionError) as refused:
            membership_services.request_membership(applicant, makerspace)
        assert refused.value.detail["code"] == "membership_invite_required"
        row = membership_services.invite_membership(actor, makerspace, applicant.email, member_role(makerspace))
        membership_services.claim_invitation(applicant, row.pk)
    else:
        row = _application(makerspace, applicant)
    row.refresh_from_db()
    if mode == "vouch":
        assert row.state == "awaiting_vouches"
        voucher, _ = _voucher(makerspace)
        vouch_for_request(voucher, row)
        row.refresh_from_db()
        assert row.state == "requested" and row.approved_at is None
        assert not MakerspaceMembership.objects.filter(makerspace=makerspace, user=applicant).exists()
    if mode != "open":
        membership_services.approve_request(actor, row, member_role(makerspace))
    row.refresh_from_db()
    if paid:
        payment = Payment.objects.get(subject_type="membership_request", subject_id=row.pk)
        assert payment.amount == plan.amount
        assert payment.provider == Payment.Provider.UNCLAIMED
        assert payment.status == Payment.Status.PENDING
        assert not payment.checkout_url and not payment.stripe_checkout_url
    else:
        assert not Payment.objects.filter(makerspace=makerspace).exists()
    if paid and timing == "before_activation":
        assert row.state == "awaiting_payment"
        assert not MakerspaceMembership.objects.filter(makerspace=makerspace, user=applicant).exists()
        mark_offline(payment, actor, settlement=settlement_details(reference="membership-desk"))
        row.refresh_from_db()
        payment.refresh_from_db()
        receipt = ManualSettlement.objects.get(payment=payment)
        assert receipt.amount == Decimal("20.00") and receipt.reference == "membership-desk"
        assert receipt.recorded_by_id == actor.pk
        assert payment.status == Payment.Status.PAID_OFFLINE
    assert row.state == "active"
    membership = MakerspaceMembership.objects.get(makerspace=makerspace, user=applicant)
    assert membership.status == "active" and membership.assigned_role_id == member_role(makerspace).pk
    term = MembershipTerm.objects.get(membership=membership)
    assert term.plan_id == plan.pk and term.ends_at > term.starts_at
    assert AuditLog.objects.filter(makerspace=makerspace, action="membership.request_activated", target_id=str(row.pk)).exists()


@pytest.mark.parametrize("timing", ["before_activation", "after_activation"])
def test_first_term_and_joining_fee_form_one_snapshotted_charge(timing):
    makerspace, actor, applicant, plan, _ = _setup(paid=True, timing=timing, joining_fee=Decimal("7.50"))
    row = _application(makerspace, applicant)
    membership_services.approve_request(actor, row, member_role(makerspace))
    row.refresh_from_db()
    payment = Payment.objects.get(pk=row.admission_payment_id)
    assert payment.amount == Decimal("27.50") and payment.currency == "usd"
    assert row.first_term_amount == Decimal("20.00") and row.joining_fee == Decimal("7.50")
    if timing == "before_activation":
        MembershipPlan.objects.filter(pk=plan.pk).update(amount=Decimal("99.00"))
        update_settings(actor, makerspace, {"joining_fee": Decimal("100.00")})
        mark_offline(payment, actor, settlement=settlement_details())
        row.refresh_from_db()
        assert row.state == "active" and row.first_term_amount == Decimal("20.00")
        assert row.joining_fee == Decimal("7.50")
    assert Payment.objects.filter(makerspace=makerspace).count() == 1


def test_invitation_claim_requires_and_snapshots_application_answers():
    schema = [{"id": "why", "label": "Why join?", "type": "paragraph", "options": [], "required": True}]
    makerspace, actor, applicant, _, _ = _setup("invite_only", application_schema=schema)
    row = membership_services.invite_membership(actor, makerspace, applicant.email, member_role(makerspace))
    with pytest.raises(ValidationError):
        membership_services.claim_invitation(applicant, row.pk)
    row.refresh_from_db()
    assert row.state == "invited" and not row.admission_managed
    membership_services.claim_invitation(applicant, row.pk, application_answers={"why": "Build accessible tools"})
    row.refresh_from_db()
    assert row.state == "requested" and row.application_schema == schema
    assert answers_for(row)["answers"][0]["value"] == "Build accessible tools"
    assert row.approved_at is None
    update_settings(actor, makerspace, {"application_schema": None})
    row.refresh_from_db()
    assert row.application_schema == schema
    membership_services.approve_request(actor, row, member_role(makerspace))
    row.refresh_from_db()
    assert row.state == "active"


@pytest.mark.parametrize("path", ["self", "invite", "referral", "anonymous_lead", "claim"])
def test_closed_refuses_every_join_path_with_typed_error(path):
    makerspace, actor, applicant, _, _ = _setup()
    referrer, _ = _voucher(makerspace)
    makerspace.referrals_enabled = True
    makerspace.save(update_fields=["referrals_enabled"])
    invitation = None
    if path == "claim":
        invitation = membership_services.invite_membership(actor, makerspace, applicant.email, member_role(makerspace))
    update_settings(actor, makerspace, {"join_mode": "closed"})
    with pytest.raises(AdmissionError) as refused:
        if path == "self":
            membership_services.request_membership(applicant, makerspace)
        elif path == "invite":
            membership_services.invite_membership(actor, makerspace, applicant.email, member_role(makerspace))
        elif path == "referral":
            membership_services.refer_membership(referrer, makerspace, applicant.email)
        elif path == "claim":
            membership_services.claim_invitation(applicant, invitation.pk)
        else:
            submit_invitation_request(makerspace, name="Applicant", email=applicant.email)
    assert refused.value.detail["code"] == "membership_closed"
    assert not MakerspaceMembership.objects.filter(makerspace=makerspace, user=applicant).exists()


def test_free_before_activation_succeeds_with_charge_tracking_disabled():
    makerspace, actor, applicant, _, _ = _setup(timing="before_activation")
    makerspace.enabled_features = [key for key in makerspace.enabled_features if key != "charges.enabled"]
    makerspace.save(update_fields=["enabled_features"])
    row = _application(makerspace, applicant)
    membership_services.approve_request(actor, row, member_role(makerspace))
    row.refresh_from_db()
    assert row.state == "active" and not Payment.objects.filter(makerspace=makerspace).exists()


def test_foreign_manager_cannot_approve_or_raise_admission_charge():
    makerspace, _, applicant, _, _ = _setup(paid=True, timing="before_activation")
    foreign = space("foreign-admission")
    outsider = manager(foreign, "foreign-admission-manager")
    row = _application(makerspace, applicant)
    with pytest.raises(PermissionDenied):
        membership_services.approve_request(outsider, row, member_role(makerspace))
    row.refresh_from_db()
    assert row.state == "requested" and row.approved_at is None
    assert not Payment.objects.filter(makerspace=makerspace).exists()
