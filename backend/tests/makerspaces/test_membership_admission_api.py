"""HTTP ownership, module gates, private answers and committed admission effects."""
from datetime import timedelta
from decimal import Decimal
from importlib import import_module

import pytest
from django.apps import apps
from django.db import connection
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.makerspaces.membership_admission_settings import update_settings
from apps.makerspaces.membership_admission_payments import sweep_admissions
from apps.makerspaces.membership_services import approve_request, request_membership
from apps.makerspaces.models import Makerspace, MakerspaceMembership, MakerspaceMembershipSettings, MakerspaceRole, MembershipPlan, MembershipRequest
from apps.payments.models import Payment
from tests.module_helpers import disable_module

pytestmark = pytest.mark.django_db(transaction=True)
QUESTION = [{"id": "why", "label": "Why join?", "type": "paragraph", "required": True, "options": []}]


def person(name):
    user = User.objects.create_user(username=name, email=f"{name}@example.test", password="password")
    user.email_verified_at = timezone.now()
    user.save(update_fields=["email_verified_at"])
    return user


def setup_space(slug="admission-api"):
    space = Makerspace.objects.create(name=slug, slug=slug)
    space.enabled_modules = list(set(space.enabled_modules or []) | {"membership"})
    space.save(update_fields=["enabled_modules"])
    manager = person(f"{slug}-manager")
    MakerspaceMembership.objects.create(makerspace=space, user=manager, assigned_role=MakerspaceRole.objects.get(makerspace=space, slug="space_manager"))
    return space, manager


def client(user=None):
    api = APIClient()
    if user:
        api.force_authenticate(user)
    return api


def test_application_schema_validates_private_snapshot_reviewer_and_own_export():
    space, manager = setup_space()
    applicant = person("api-applicant")
    update_settings(manager, space, {"join_mode": "approval", "application_schema": QUESTION})
    url = f"/api/v1/public/{space.slug}/membership-requests"
    assert client().post(url, {}, format="json").status_code == 401
    assert client(applicant).post(url, {}, format="json").status_code == 400
    response = client(applicant).post(url, {"application_answers": {"why": "Build a robot"}}, format="json")
    assert response.status_code == 201
    row = MembershipRequest.objects.get(pk=response.data["request_id"])
    review = client(manager).get(f"/api/v1/admin/membership-requests?makerspace_id={space.pk}")
    assert review.status_code == 200
    assert review.data["results"][0]["application_answers"]["answers"][0]["value"] == "Build a robot"
    export_url = f"/api/v1/member/makerspaces/{space.pk}/admission/export"
    own = client(applicant).get(export_url)
    assert own.status_code == 200
    assert own.data["requests"][0]["application_answers"]["answers"][0]["label"] == "Why join?"
    assert client(person("api-other")).get(export_url).data == {"requests": []}
    assert AuditLog.objects.filter(action="membership.application_exported", actor=applicant).exists()
    public = client().get(f"/api/v1/public/{space.slug}/membership-admission")
    assert public.status_code == 200 and "application_answers" not in public.data
    assert row.application_schema == QUESTION


def test_admission_settings_rbac_foreign_plan_and_recipe_overrides():
    space, manager = setup_space("admission-settings")
    other, foreign_manager = setup_space("admission-foreign")
    foreign_plan = MembershipPlan.objects.create(makerspace=other, name="Foreign", interval="monthly")
    url = f"/api/v1/admin/makerspaces/{space.pk}/membership-admission"
    assert client(foreign_manager).get(url).status_code == 404
    assert client(manager).patch(url, {"default_plan": foreign_plan.pk}, format="json").status_code == 400
    response = client(manager).patch(url, {"recipe": "free_vouch", "vouches_required": 2}, format="json")
    assert response.status_code == 200
    assert response.data["join_mode"] == "vouch" and response.data["vouches_required"] == 2
    assert response.data["voucher_min_tenure_days"] == 30
    assert response.data["voucher_pending_limit"] == 3
    space.refresh_from_db()
    assert "membership.vouching" in space.enabled_features


def test_unpaid_expiry_cancels_charge_and_releases_open_request_slot():
    space, manager = setup_space("admission-expiry")
    applicant = person("expiry-applicant")
    plan = MembershipPlan.objects.create(makerspace=space, name="Paid", interval="monthly", amount=10)
    update_settings(manager, space, {"join_mode": "open", "payment_timing": "before_activation", "default_plan": plan})
    result = request_membership(applicant, space)
    row = MembershipRequest.objects.get(pk=result["request_id"])
    assert row.state == "awaiting_payment"
    counts = sweep_admissions(now=row.expires_at + timedelta(seconds=1))
    row.refresh_from_db()
    row.admission_payment.refresh_from_db()
    assert counts["expired"] == 1 and row.state == "expired"
    assert row.admission_payment.status == "canceled"
    assert not MakerspaceMembership.objects.filter(makerspace=space, user=applicant).exists()
    assert request_membership(applicant, space)["request_id"] != row.pk
    assert AuditLog.objects.filter(action="membership.expired", target_id=str(row.pk)).exists()


def test_applicant_cancellation_ownership_and_module_off_400():
    space, manager = setup_space("admission-cancel")
    applicant = person("cancel-applicant")
    update_settings(manager, space, {"join_mode": "approval"})
    result = request_membership(applicant, space)
    url = f"/api/v1/member/makerspaces/{space.pk}/admission/{result['request_id']}/cancel"
    assert client(person("cancel-other")).post(url).status_code == 404
    assert client(applicant).post(url).data["state"] == "canceled"
    assert client(applicant).post(url).status_code == 400
    disable_module(space, "membership")
    assert client().get(f"/api/v1/public/{space.slug}/membership-admission").status_code == 400
    assert client(applicant).post(f"/api/v1/public/{space.slug}/membership-requests", {}, format="json").status_code == 400
    assert client(applicant).get(f"/api/v1/member/makerspaces/{space.pk}/admission").status_code == 400


def test_backfill_copies_all_old_policies_without_opt_in_or_plan():
    migration = import_module("apps.makerspaces.migrations.0080_membership_admission")
    spaces = [Makerspace.objects.create(name=f"old-{mode}", slug=f"old-{mode}", membership_policy=mode,
                                       membership_dues_amount=Decimal("12.50"), referrals_enabled=True)
              for mode in ("request", "open", "invite_only")]
    MakerspaceMembershipSettings.objects.filter(makerspace__in=spaces).delete()
    with connection.schema_editor() as editor:
        migration.backfill(apps, editor)
    for space in spaces:
        policy = MakerspaceMembershipSettings.objects.get(makerspace=space)
        assert not policy.configured and policy.default_plan_id is None
        assert policy.join_mode == ("approval" if space.membership_policy == "request" else space.membership_policy)
        assert policy.joining_fee == Decimal("12.50") and policy.payment_timing == "after_activation"
        assert policy.rejoin_dues_rule == "once"
    joined = request_membership(person("legacy-open"), spaces[1])
    assert joined["outcome"] == "joined"
    charge = Payment.objects.get(subject_type="makerspace_membership", subject_id=joined["membership_id"])
    # Legacy admission retains dues tracking independently of the optional online rail.
    assert charge.amount == Decimal("12.50") and charge.status == "pending"
    assert charge.provider == Payment.Provider.UNCLAIMED


def test_preconfiguration_application_keeps_its_submission_policy():
    space, manager = setup_space("admission-grandfather")
    applicant = person("grandfather-applicant")
    outcome = request_membership(applicant, space)
    row = MembershipRequest.objects.get(pk=outcome["request_id"])
    update_settings(manager, space, {"join_mode": "approval", "application_schema": QUESTION})
    role = MakerspaceRole.objects.get(makerspace=space, slug="member")
    result = approve_request(manager, row, role)
    assert result.status == "active"
    row.refresh_from_db()
    assert row.application_answers is None and not row.admission_managed


def test_pending_payment_approval_http_has_request_shape_and_foreign_actor_is_refused():
    space, manager = setup_space("admission-approve-http")
    applicant = person("approve-http-applicant")
    plan = MembershipPlan.objects.create(makerspace=space, name="Paid", interval="monthly", amount=10)
    update_settings(manager, space, {"join_mode": "approval", "payment_timing": "before_activation", "default_plan": plan})
    result = request_membership(applicant, space)
    url = f"/api/v1/admin/membership-requests/{result['request_id']}/approve"
    role = MakerspaceRole.objects.get(makerspace=space, slug="member")
    other, other_manager = setup_space("admission-approve-other")
    assert client(other_manager).post(url, {"role_id": role.pk}, format="json").status_code == 404
    response = client(manager).post(url, {"role_id": role.pk}, format="json")
    assert response.status_code == 200 and response.data["state"] == "awaiting_payment"
    assert response.data["admission_payment"]["amount"] == "10.00"
    own = client(applicant).get("/api/v1/memberships/me")
    assert own.data["requests"][0]["id"] == result["request_id"]
    assert own.data["requests"][0]["admission_payment"]["status"] == "pending"


@pytest.mark.parametrize("paid", [False, True])
def test_voucher_response_never_contains_private_answers_or_payment(paid):
    from tests.makerspaces.test_membership_admission_matrix import _setup, _voucher
    space, _, applicant, _, _ = _setup(
        "vouch", paid, "before_activation", application_schema=QUESTION,
        vouch_replaces_approval=paid,
    )
    outcome = request_membership(applicant, space, {"why": "Private application"})
    voucher, _ = _voucher(space)
    response = client(voucher).post(f"/api/v1/member/makerspaces/{space.pk}/admission/{outcome['request_id']}/vouch")
    assert response.status_code == 200
    assert response.data == {
        "id": outcome["request_id"],
        "state": "awaiting_payment" if paid else "requested",
    }


def test_existing_settings_patch_fields_remain_aliases_after_configuration():
    space, manager = setup_space("admission-aliases")
    update_settings(manager, space, {"join_mode": "closed"})
    response = client(manager).patch(f"/api/v1/admin/makerspaces/{space.pk}", {
        "membership_policy": "open", "membership_dues_amount": "5.00",
    }, format="json")
    assert response.status_code == 200
    policy = MakerspaceMembershipSettings.objects.get(makerspace=space)
    assert policy.join_mode == "open" and policy.joining_fee == Decimal("5.00")
    assert request_membership(person("alias-applicant"), space)["outcome"] == "joined"


def test_configured_invitation_cannot_bypass_claim_form_and_payment_by_staff_approval():
    from apps.makerspaces.membership_admission_settings import AdmissionError
    from apps.makerspaces.membership_services import invite_membership
    space, manager = setup_space("admission-unclaimed")
    applicant = person("unclaimed-applicant")
    update_settings(manager, space, {"join_mode": "invite_only", "application_schema": QUESTION})
    role = MakerspaceRole.objects.get(makerspace=space, slug="member")
    row = invite_membership(manager, space, applicant.email, role)
    with pytest.raises(AdmissionError) as refused:
        approve_request(manager, row, role)
    assert refused.value.detail["code"] == "membership_invitation_unclaimed"
    assert not MakerspaceMembership.objects.filter(makerspace=space, user=applicant).exists()


def test_module_off_suspends_admission_expiry_without_altering_core_memberships():
    from tests.makerspaces.test_membership_admission_matrix import _setup
    space, _, applicant, _, _ = _setup("open", True, "before_activation")
    result = request_membership(applicant, space)
    row = MembershipRequest.objects.get(pk=result["request_id"])
    disable_module(space, "membership")
    counts = sweep_admissions(now=row.expires_at + timedelta(seconds=1))
    row.refresh_from_db()
    assert counts["expired"] == 0 and counts["failed"] == 0
    assert row.state == "awaiting_payment" and row.admission_payment.status == "pending"
