"""Renewal predecessor uniqueness must follow the imported identity mapping."""
import pytest

from apps.tenant_migration.projection_guards import ProjectionRegistryError, validate_unique_constraint_risks
from apps.tenant_migration.unique_values import DEPLOYMENT_GLOBAL_UNIQUE_RULES, REMAP


def test_renewal_predecessor_is_remapped_and_missing_policy_fails_closed():
    edge = ("makerspaces.MembershipTerm", "field:renewed_from")
    assert DEPLOYMENT_GLOBAL_UNIQUE_RULES[edge].disposition is REMAP
    policies = dict(DEPLOYMENT_GLOBAL_UNIQUE_RULES)
    policies.pop(edge)
    with pytest.raises(ProjectionRegistryError, match="renewed_from"):
        validate_unique_constraint_risks(policies)
