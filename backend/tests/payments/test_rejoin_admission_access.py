"""The new admission charge never restores a revoked member's old money access."""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.accounts.models import User
from apps.makerspaces.models import MakerspaceMembership, MembershipRequest
from apps.payments.admission_access import admission_payment_queryset
from apps.payments.member_access import member_may_see_own_charges
from apps.payments.member_scope import member_payment_queryset
from apps.payments.models import Payment
from tests.module_helpers import disable_module
from tests.return_helpers import authenticated_client, make_member, make_space, make_user

pytestmark = pytest.mark.django_db


def rejoining_applicant():
    space = make_space("rejoin-own-charge")
    manager = make_member("rejoin-own-manager", space)
    applicant = make_member("rejoin-own-applicant", space,
                            membership_role=MakerspaceMembership.Role.MEMBER,
                            role=User.Role.REQUESTER)
    membership = MakerspaceMembership.objects.get(makerspace=space, user=applicant)
    membership.status = "revoked"
    membership.save(update_fields=["status"])
    old_charge = Payment.objects.create(
        makerspace=space, subject_type="makerspace_membership", subject_id=membership.pk,
        member=applicant, amount="9", currency="usd", created_by=manager,
    )
    now = timezone.now()
    request = MembershipRequest.objects.create(
        makerspace=space, user=applicant, requested_by=applicant, kind="request",
        state="awaiting_payment", admission_managed=True, approved_at=now,
        expires_at=now + timedelta(days=7), rejoining=True,
    )
    charge = Payment.objects.create(
        makerspace=space, subject_type="membership_request", subject_id=request.pk,
        member=applicant, amount="12", currency="usd", created_by=manager,
        stripe_checkout_session_id="cs_rejoin", stripe_checkout_url="https://example.test/new-admission",
    )
    request.admission_payment = charge
    request.save(update_fields=["admission_payment"])
    return space, applicant, request, charge, old_charge


def test_rejoining_revoked_applicant_reads_only_new_admission_charge():
    space, applicant, request, charge, old_charge = rejoining_applicant()
    assert member_may_see_own_charges(applicant, space.pk)
    assert list(member_payment_queryset(applicant, space.pk).values_list("pk", flat=True)) == [charge.pk]
    response = authenticated_client(applicant).get(f"/api/v1/member/makerspaces/{space.pk}/payments")
    assert response.status_code == 200
    assert [row["id"] for row in response.data] == [charge.pk]


def test_rejoin_web_checkout_is_new_charge_only():
    space, applicant, request, charge, old_charge = rejoining_applicant()
    client = authenticated_client(applicant)
    base = f"/api/v1/member/makerspaces/{space.pk}/payments"
    assert client.post(f"{base}/{old_charge.pk}/checkout").status_code == 404
    response = client.post(f"{base}/{charge.pk}/checkout")
    assert response.status_code == 200
    assert response.data["checkout_url"] == "https://example.test/new-admission"


@pytest.mark.parametrize("change", ["unapproved", "expired", "canceled", "legacy", "settled"])
def test_rejoin_money_exception_requires_live_approved_managed_pending_application(change):
    space, applicant, request, charge, old_charge = rejoining_applicant()
    if change == "settled":
        charge.status = Payment.Status.WAIVED
        charge.save(update_fields=["status", "updated_at"])
    else:
        updates = {"unapproved": {"approved_at": None},
                   "expired": {"expires_at": timezone.now() - timedelta(seconds=1)},
                   "canceled": {"state": "canceled"},
                   "legacy": {"admission_managed": False}}[change]
        MembershipRequest.objects.filter(pk=request.pk).update(**updates)
    assert not member_may_see_own_charges(applicant, space.pk)
    assert not member_payment_queryset(applicant, space.pk).exists()


@pytest.mark.parametrize("change", ["restricted", "inactive", "module_off", "other_user", "other_tenant"])
def test_rejoin_money_exception_preserves_account_tenant_and_module_gates(change):
    space, applicant, request, charge, old_charge = rejoining_applicant()
    if change == "restricted":
        applicant.access_status = "restricted"
        applicant.save(update_fields=["access_status"])
    elif change == "inactive":
        applicant.is_active = False
        applicant.save(update_fields=["is_active"])
    elif change == "module_off":
        disable_module(space, "membership")
    elif change == "other_user":
        applicant = make_user("rejoin-other-user", access_status="active")
    else:
        space = make_space("rejoin-other-space")
    assert not admission_payment_queryset(applicant, space.pk).exists()
    assert not member_may_see_own_charges(applicant, space.pk)


def test_reactivation_restores_ordinary_own_money_history():
    space, applicant, request, charge, old_charge = rejoining_applicant()
    MakerspaceMembership.objects.filter(makerspace=space, user=applicant).update(status="active")
    assert set(member_payment_queryset(applicant, space.pk).values_list("pk", flat=True)) == {
        charge.pk, old_charge.pk,
    }
