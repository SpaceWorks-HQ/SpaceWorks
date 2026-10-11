import pytest
from django.urls import reverse

from apps.makerspaces.models import MakerspaceMembership
from tests.modules.family_helpers import account, assert_family_bootstrap, client, family_space

pytestmark = pytest.mark.django_db


def test_membership_only_activity_and_bootstrap_survive_without_loans():
    space = family_space("family-membership", "membership", "member_accounts")
    member = account("family-member")
    MakerspaceMembership.objects.create(makerspace=space, user=member, status="active")
    result = client(member).get(f"/api/v1/member/makerspaces/{space.pk}/activity")
    assert result.status_code == 200, result.data
    assert_family_bootstrap(space, "membership")
    assert client(member).post(reverse("hardware_requests:request-submit", args=[space.slug]), {}, format="json").status_code == 400


def test_membership_only_join_paid_admission_offline_settlement_and_card(django_capture_on_commit_callbacks):
    from django.utils import timezone
    from apps.audit.models import AuditLog
    from apps.makerspaces.membership_admission_settings import update_settings
    from apps.makerspaces.member_card_services import issue_card
    from apps.makerspaces.models import MembershipPlan, MembershipRequest, MembershipTerm
    from apps.payments.models import ManualSettlement, Payment
    from tests.return_helpers import settlement_payload

    space = family_space("family-paid-membership", "membership", "member_accounts")
    manager, applicant = account("family-admission-manager", staff=True), account("family-admission-applicant")
    applicant.email_verified_at = timezone.now()
    applicant.save(update_fields=["email_verified_at"])
    plan = MembershipPlan.objects.create(makerspace=space, name="Monthly", interval="monthly", amount="20.00", currency="usd")
    plan.refresh_from_db()
    update_settings(manager, space, {"join_mode": "open", "payment_timing": "before_activation", "default_plan": plan})
    joined = client(applicant).post(f"/api/v1/public/{space.slug}/membership-requests", {}, format="json")
    assert joined.status_code == 201, joined.data
    request = MembershipRequest.objects.get(makerspace=space, user=applicant)
    assert request.state == "awaiting_payment"
    charge = Payment.objects.get(pk=request.admission_payment_id)
    assert charge.provider == "unclaimed" and charge.amount == plan.amount
    assert not MakerspaceMembership.objects.filter(makerspace=space, user=applicant).exists()
    with django_capture_on_commit_callbacks(execute=True):
        settled = client(manager).post(reverse("payment-reconciliation-mark-offline", args=[space.pk, charge.pk]),
            settlement_payload(), format="json")
    assert settled.status_code == 200, settled.data
    assert ManualSettlement.objects.get(payment=charge).recorded_by == manager
    membership = MakerspaceMembership.objects.get(makerspace=space, user=applicant, status="active")
    assert MembershipTerm.objects.get(membership=membership).plan_id == plan.pk
    card = issue_card(manager, membership)
    own_card = client(applicant).get(reverse("member-card", args=[space.pk]))
    assert own_card.status_code == 200, own_card.data
    assert own_card.data["id"] == card.pk
    assert AuditLog.objects.filter(makerspace=space, action="member_card.issued", actor=manager).exists()
    assert "payments" not in space.enabled_modules
    assert_family_bootstrap(space, "membership")
