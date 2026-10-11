"""Shared audited loan-policy writer for the settings editor and packs."""
from django.db import transaction

from apps.accounts import rbac
from apps.admin_api.permissions import require_action
from apps.admin_api.serializers_loan_policy import ReturnPolicySerializer
from apps.audit import services as audit
from apps.tenant_migration.gate_runtime import assert_write_allowed
from .guards import require_module_locked
from .models_loan_policy import MakerspaceLoanPolicy


@transaction.atomic
def update_loan_policy(actor, makerspace, values):
    assert_write_allowed(makerspace.pk)
    makerspace = require_module_locked(makerspace, "request_workflow")
    require_action(actor, rbac.Action.MANAGE_MAKERSPACE, makerspace.pk)
    policy = MakerspaceLoanPolicy.for_makerspace(makerspace)
    before = {key: value for key, value in ReturnPolicySerializer(policy).data.items() if key != "id"}
    serializer = ReturnPolicySerializer(policy, data=values, partial=True)
    serializer.is_valid(raise_exception=True)
    policy = serializer.save()
    makerspace.default_loan_days = policy.default_loan_days
    makerspace.save(update_fields=["default_loan_days"])
    audit.record(actor, "makerspace.return_policy_updated", makerspace=makerspace,
                 target=policy, meta={"before": before, "after": {
                     key: value for key, value in serializer.data.items() if key != "id"
                 }})
    return policy
