from datetime import timedelta

import pytest
from django.core.exceptions import ValidationError as ModelValidationError
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.admin_api.serializers_loan_policy import ReturnPolicySerializer
from apps.audit.models import AuditLog
from apps.data_export.datasets import DATASET_SPECS
from apps.hardware_requests import workflow
from apps.inventory import availability
from apps.inventory.models import Category
from apps.makerspaces.loan_policy import loan_days, renewal_cap
from apps.makerspaces.models import MembershipPlan, MembershipTerm
from apps.makerspaces.models_loan_policy import MakerspaceLoanPolicy
from apps.tenant_migration.tenant_dump_field_snapshot import FIRST_PARTY_FIELD_NAMES
from apps.tenant_migration.tenant_dump_model_catalog import FIRST_PARTY_MODEL_RULES
from tests.hardware_requests.loan_policy_helpers import setup_loan
from tests.return_helpers import make_member, make_space, make_product

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("data", [
    {"default_loan_days": 0}, {"default_loan_days": 366}, {"loan_renewal_days": 0},
    {"loan_max_renewals": -1}, {"loan_renewal_mode": "staff_approve"},
    {"loan_max_active": -1}, {"loan_max_items": -1},
    {"loan_reminder_offsets_hours": "0"}, {"loan_reminder_offsets_hours": [True]},
    {"loan_reminder_offsets_hours": [1.5]}, {"loan_reminder_offsets_hours": [0, 0]},
    {"loan_reminder_offsets_hours": [8761]}, {"loan_reminder_offsets_hours": list(range(101))},
    {"loan_escalate_overdue_days": 366},
])
def test_policy_rejects_invalid_boundaries(data):
    assert not ReturnPolicySerializer(data=data, partial=True).is_valid()


def test_policy_model_validates_offsets_and_defaults_without_creating_row():
    space = make_space("policy-defaults")
    space.default_loan_days = 9
    space.save(update_fields=["default_loan_days"])
    policy = MakerspaceLoanPolicy.for_makerspace(space)
    assert policy.default_loan_days == 9
    assert policy.loan_reminder_offsets_hours == [0]
    assert policy.loan_escalate_overdue_days == 0
    assert policy.loan_renewal_mode == "off"
    assert not MakerspaceLoanPolicy.objects.exists()
    policy.loan_reminder_offsets_hours = [False]
    with pytest.raises(ModelValidationError):
        policy.clean_fields()


def test_policy_patch_is_scoped_audited_and_keeps_legacy_days_coherent():
    space = make_space("policy-staff")
    staff = make_member("policy-staff", space)
    from rest_framework.test import APIClient

    client = APIClient()
    client.force_authenticate(staff)
    path = f"/api/v1/admin/makerspace/{space.pk}/return-policy"
    assert client.get(path).status_code == 200
    assert not MakerspaceLoanPolicy.objects.filter(makerspace=space).exists()
    response = client.patch(path, {"default_loan_days": 3, "loan_reminder_offsets_hours": [-24, 0, 24]}, format="json")
    assert response.status_code == 200
    space.refresh_from_db()
    assert space.default_loan_days == 3
    assert MakerspaceLoanPolicy.objects.get(makerspace=space).default_loan_days == 3
    entry = AuditLog.objects.get(actor=staff, action="makerspace.return_policy_updated", makerspace=space)
    from apps.audit.presentation import project_meta

    projected, redacted = project_meta(entry.action, entry.meta)
    assert projected["before"]["default_loan_days"] == 7
    assert projected["after"]["loan_reminder_offsets_hours"] == [-24, 0, 24]
    assert not redacted
    other = make_space("policy-other")
    assert client.patch(f"/api/v1/admin/makerspace/{other.pk}/return-policy", {"default_loan_days": 2}, format="json").status_code == 404
    space.default_loan_days = 4
    space.save(update_fields=["default_loan_days"])
    assert MakerspaceLoanPolicy.for_makerspace(space).default_loan_days == 4


def test_period_and_cap_inherit_product_then_category_then_space():
    space = make_space("periods")
    policy = MakerspaceLoanPolicy.objects.create(makerspace=space, default_loan_days=5, loan_max_renewals=1)
    product = make_product(space)
    assert loan_days(space, [product]) == 5
    category = Category.objects.create(makerspace=space, name="Fast", slug="fast", loan_days=2, max_renewals=3)
    product.category = category
    assert loan_days(space, [product]) == 2
    assert renewal_cap(policy, [product]) == 3
    product.loan_days, product.max_renewals = 1, 0
    assert loan_days(space, [product]) == 1
    assert renewal_cap(policy, [product]) == 0


def test_loan_policy_is_classified_without_user_closure():
    label = "makerspaces.MakerspaceLoanPolicy"
    assert label in DATASET_SPECS and label in FIRST_PARTY_MODEL_RULES
    assert FIRST_PARTY_FIELD_NAMES[label] == frozenset(field.name for field in MakerspaceLoanPolicy._meta.fields)
    assert not any(field.is_relation and field.related_model._meta.label == "accounts.User"
                   for field in MakerspaceLoanPolicy._meta.fields)


def test_borrow_limits_are_opt_in_and_count_outstanding_items():
    space, member, _, _, request, policy, _ = setup_loan("limits")
    policy.loan_max_active = 1
    policy.save()
    with pytest.raises(ValidationError, match="active-loan"):
        availability.enforce_borrow_limits(space, member, 1)
    policy.loan_max_active, policy.loan_max_items = 0, 1
    policy.save()
    with pytest.raises(ValidationError, match="item limit"):
        availability.enforce_borrow_limits(space, member, 1)
    space.enabled_features.remove("loans.limits")
    space.save(update_fields=["enabled_features"])
    availability.enforce_borrow_limits(space, member, 10)


def test_current_plan_overrides_borrow_limits():
    space, member, membership, _, _, policy, _ = setup_loan("plan-limits")
    policy.loan_max_active = 1
    policy.save()
    plan = MembershipPlan.objects.create(makerspace=space, name="Unlimited", interval="monthly", loan_max_active=0)
    MembershipTerm.objects.create(membership=membership, plan=plan, starts_at=timezone.now() - timedelta(days=1),
                                  ends_at=timezone.now() + timedelta(days=30))
    availability.enforce_borrow_limits(space, member, 1)


def test_issue_limit_counts_only_items_actually_handed_over_after_rejects():
    space, member, _, _, loan, policy, _ = setup_loan("limit-rejects")
    loan.status = "accepted"
    loan.save(update_fields=["status"])
    item = loan.items.get()
    item.requested_quantity = item.accepted_quantity = 3
    item.issued_quantity = 0
    item.save()
    policy.loan_max_items = 2
    policy.save()
    with pytest.raises(ValidationError):
        availability.enforce_request_borrow_limits(loan)
    availability.enforce_request_borrow_limits(loan, {item.pk: (1, "needs_fix")})


def test_policy_endpoint_answers_400_when_workflow_module_is_off():
    space, _, _, _, _, _, client = setup_loan("policy-module-off")
    client.force_authenticate(make_member("policy-off-staff", space))
    space.enabled_modules.remove("request_workflow")
    space.save(update_fields=["enabled_modules"])
    path = f"/api/v1/admin/makerspace/{space.pk}/return-policy"
    assert client.get(path).status_code == 400
    assert client.patch(path, {"default_loan_days": 3}, format="json").status_code == 400
