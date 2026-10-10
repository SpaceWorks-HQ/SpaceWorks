from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.audit.models import AuditLog
from apps.hardware_requests import workflow
from apps.hardware_requests.models import HardwareRequest, HardwareRequestItem, PublicToolLoan
from apps.makerspaces.models import MakerspaceMembership, MembershipPlan, MembershipTerm
from apps.makerspaces.member_loans import member_loans
from tests.hardware_requests.loan_policy_helpers import setup_loan
from tests.return_helpers import make_member, make_space, make_user

pytestmark = pytest.mark.django_db


def test_member_renewal_extends_both_due_dates_without_status_transition_and_audits():
    space, member, _, _, loan, policy, client = setup_loan("renew")
    due = loan.return_due_at
    response = client.post(f"/api/v1/member/makerspaces/{space.pk}/loans/{loan.pk}/renew", {}, format="json")
    assert response.status_code == 200
    loan.refresh_from_db()
    assert loan.return_due_at == due + timedelta(days=policy.loan_renewal_days)
    assert loan.renewal_count == 1 and loan.status == "issued"
    assert PublicToolLoan.objects.get(request=loan).due_at == loan.return_due_at
    assert AuditLog.objects.filter(actor=member, action="request.renewed", makerspace=space).exists()
    assert client.post(f"/api/v1/member/makerspaces/{space.pk}/loans/{loan.pk}/renew", {}, format="json").status_code == 400


def test_staff_renewal_uses_the_same_policy_and_can_renew_reviewed_loans():
    space, _, _, _, loan, _, client = setup_loan("staff-renew", linked=False)
    staff = make_member("renew-manager", space)
    client.force_authenticate(staff)
    path = f"/api/v1/admin/makerspace/{space.pk}/loans/{loan.pk}/renew"
    assert client.post(path, {}, format="json").status_code == 200
    assert client.post(path, {}, format="json").status_code == 400


@pytest.mark.parametrize("restriction", ["inactive", "restricted", "password"])
def test_ineligible_staff_cannot_renew_another_borrowers_loan(restriction):
    space, _, _, _, loan, _, client = setup_loan(f"staff-refused-{restriction}")
    staff = make_member(f"staff-refused-{restriction}", space)
    if restriction == "inactive":
        staff.is_active = False
    elif restriction == "restricted":
        staff.access_status = "restricted"
    else:
        staff.must_change_password = True
    staff.save()
    client.force_authenticate(staff)
    assert client.post(f"/api/v1/admin/makerspace/{space.pk}/loans/{loan.pk}/renew", {}, format="json").status_code == 403
    with pytest.raises(PermissionDenied):
        workflow.renew_loan(staff, loan, staff=True)


@pytest.mark.parametrize("condition,code", [
    ("restricted", "borrower_restricted"), ("lapsed", "membership_lapsed"),
    ("max", "renewal_limit"), ("waiting", "request_waiting"),
    ("returned", "loan_not_active"), ("no_due", "loan_not_active"), ("off", "renewals_off"),
])
def test_renewal_refusals_leave_due_date_and_audit_unchanged(condition, code):
    space, member, membership, product, loan, policy, _ = setup_loan(f"refuse-{condition}")
    if condition == "restricted":
        member.access_status = "restricted"
        member.save(update_fields=["access_status"])
    elif condition == "lapsed":
        plan = MembershipPlan.objects.create(makerspace=space, name="Plan", interval="monthly")
        MembershipTerm.objects.create(membership=membership, plan=plan,
                                      starts_at=timezone.now() - timedelta(days=31), ends_at=timezone.now() - timedelta(days=1))
    elif condition == "max":
        loan.renewal_count = policy.loan_max_renewals
        loan.save(update_fields=["renewal_count"])
    elif condition == "waiting":
        other = make_user("waiting-borrower")
        waiting = HardwareRequest.objects.create(makerspace=space, requester=other, requester_username=other.username)
        HardwareRequestItem.objects.create(request=waiting, product=product, requested_quantity=1)
    elif condition == "returned":
        loan.status = "returned"
        loan.save(update_fields=["status"])
    elif condition == "no_due":
        loan.return_due_at = None
        loan.save(update_fields=["return_due_at"])
    else:
        policy.loan_renewal_mode = "off"
        policy.save()
    staff = make_member(f"manager-{condition}", space)
    old_due = loan.return_due_at
    with pytest.raises(ValidationError) as error:
        workflow.renew_loan(staff, loan, staff=True)
    assert error.value.detail["code"] == code
    loan.refresh_from_db()
    assert loan.return_due_at == old_due
    assert not AuditLog.objects.filter(action="request.renewed", makerspace=space).exists()


def test_other_members_and_other_tenants_cannot_renew():
    space, _, _, _, loan, _, client = setup_loan("owner-only")
    other = make_member("other-owner", space)
    client.force_authenticate(other)
    assert client.post(f"/api/v1/member/makerspaces/{space.pk}/loans/{loan.pk}/renew", {}, format="json").status_code == 404
    alien_space = make_space("alien-loan")
    alien_staff = make_member("alien-staff", alien_space)
    client.force_authenticate(alien_staff)
    assert client.post(f"/api/v1/admin/makerspace/{space.pk}/loans/{loan.pk}/renew", {}, format="json").status_code == 404
    with pytest.raises(PermissionDenied):
        workflow.renew_loan(alien_staff, loan, staff=True)


@pytest.mark.parametrize("gate", ["membership", "request_workflow", "loans.renewals"])
def test_member_renew_module_or_feature_off_returns_400(gate):
    space, _, _, _, loan, _, client = setup_loan(f"gate-{gate.replace('.', '-')}")
    field = "enabled_features" if gate.startswith("loans.") else "enabled_modules"
    values = list(getattr(space, field))
    values.remove(gate)
    setattr(space, field, values)
    space.save(update_fields=[field])
    assert client.post(f"/api/v1/member/makerspaces/{space.pk}/loans/{loan.pk}/renew", {}, format="json").status_code == 400


def test_dashboard_includes_reviewed_loans_and_renewal_eligibility():
    space, member, _, _, loan, _, _ = setup_loan("dashboard-renew", linked=False)
    rows = member_loans(space, member, timezone.now())
    assert rows[0]["request_id"] == loan.pk and rows[0]["can_renew"]
    workflow.renew_loan(member, loan)
    assert not member_loans(space, member, timezone.now())[0]["can_renew"]


def test_accepted_request_with_matching_declined_item_does_not_block_renewal():
    space, member, _, product, loan, _, _ = setup_loan("declined-waiting")
    other = make_user("accepted-other")
    waiting = HardwareRequest.objects.create(makerspace=space, requester=other,
                                              requester_username=other.username, status="accepted")
    HardwareRequestItem.objects.create(request=waiting, product=product, requested_quantity=1,
                                       accepted_quantity=0)
    from tests.return_helpers import make_product

    other_product = make_product(space)
    HardwareRequestItem.objects.create(request=waiting, product=other_product, requested_quantity=1,
                                       accepted_quantity=1)
    workflow.renew_loan(member, loan)
    loan.refresh_from_db()
    assert loan.renewal_count == 1


def test_partial_return_does_not_block_on_already_returned_product():
    space, member, _, product, loan, _, _ = setup_loan("partial-renew")
    from tests.return_helpers import make_product

    remaining = make_product(space)
    item = loan.items.get()
    item.returned_quantity = item.issued_quantity
    item.save(update_fields=["returned_quantity"])
    HardwareRequestItem.objects.create(request=loan, product=remaining, requested_quantity=1,
                                       accepted_quantity=1, issued_quantity=1)
    loan.status = "partially_returned"
    loan.save(update_fields=["status"])
    other = make_user("partial-waiter")
    waiting = HardwareRequest.objects.create(makerspace=space, requester=other, requester_username=other.username)
    HardwareRequestItem.objects.create(request=waiting, product=product, requested_quantity=1)
    assert workflow.renew_loan(member, loan).renewal_count == 1


def test_future_membership_term_cannot_authorize_renewal():
    space, member, membership, _, loan, _, _ = setup_loan("future-term")
    plan = MembershipPlan.objects.create(makerspace=space, name="Future", interval="monthly")
    MembershipTerm.objects.create(membership=membership, plan=plan,
                                  starts_at=timezone.now() + timedelta(days=1), ends_at=timezone.now() + timedelta(days=31))
    with pytest.raises(ValidationError, match="membership_lapsed"):
        workflow.renew_loan(member, loan)


def test_manual_due_change_keeps_linked_loan_coherent_without_using_renewal_slot():
    space, _, _, _, loan, _, _ = setup_loan("manual-due")
    staff = make_member("manual-due-manager", space)
    due = loan.return_due_at + timedelta(days=3)
    updated = workflow.set_return_due(staff, loan, due)
    assert updated.return_due_at == due and updated.renewal_count == 0
    assert PublicToolLoan.objects.get(request=loan).due_at == due


def test_renewal_rejects_non_object_payload_without_audit():
    space, _, _, _, loan, _, client = setup_loan("renew-body")
    response = client.post(f"/api/v1/member/makerspaces/{space.pk}/loans/{loan.pk}/renew", [], format="json")
    assert response.status_code == 400
    assert not AuditLog.objects.filter(makerspace=space, action="request.renewed").exists()


def test_renewal_refuses_datetime_overflow_without_changing_due_date():
    from datetime import datetime, timezone as datetime_timezone

    space, member, _, _, loan, _, _ = setup_loan("renew-overflow")
    loan.return_due_at = datetime.max.replace(tzinfo=datetime_timezone.utc)
    loan.save(update_fields=["return_due_at"])
    with pytest.raises(ValidationError, match="due_date_out_of_range"):
        workflow.renew_loan(member, loan)
    loan.refresh_from_db()
    assert loan.return_due_at == datetime.max.replace(tzinfo=datetime_timezone.utc)
    assert loan.renewal_count == 0
    assert not AuditLog.objects.filter(makerspace=space, action="request.renewed").exists()


def test_staff_renewal_checks_browser_origin_even_with_authority_in_both_spaces():
    space, _, _, _, loan, _, client = setup_loan("renew-origin")
    staff = make_member("renew-origin-staff", space)
    other = make_space("renew-origin-other")
    MakerspaceMembership.objects.create(makerspace=other, user=staff, role="space_manager")
    for row in (space, other):
        row.frontend_domain = f"{row.slug}.example.test"
        row.frontend_domain_status = "verified"
        row.save(update_fields=["frontend_domain", "frontend_domain_status"])
    client.force_authenticate(staff)
    path = f"/api/v1/admin/makerspace/{space.pk}/loans/{loan.pk}/renew"
    assert client.post(path, {}, format="json", HTTP_ORIGIN=f"https://{other.frontend_domain}").status_code == 403
    assert client.post(path, {}, format="json", HTTP_ORIGIN=f"https://{space.frontend_domain}").status_code == 200
