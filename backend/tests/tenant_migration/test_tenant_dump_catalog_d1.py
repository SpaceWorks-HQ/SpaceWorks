import pytest
from django.db import models
from django.test.utils import isolate_apps

from apps.tenant_migration.tenant_dump_authority import (
    AUTHORITY_FIELD_OVERRIDES,
)
from apps.tenant_migration.tenant_dump_catalog import (
    FIELD_POLICIES,
    TenantDumpCatalogError,
    validate_catalog,
    validate_field_coverage,
)
from apps.tenant_migration.tenant_dump_types import (
    AuthorityDisposition,
    AuthorityField,
    NoAuthorityField,
)


def test_every_field_in_the_live_model_graph_has_a_disposition():
    validate_catalog()
    assert FIELD_POLICIES
    assert all(
        isinstance(rule, (AuthorityField, NoAuthorityField)) and rule.reason
        for rule in FIELD_POLICIES.values()
    )


@isolate_apps()
def test_unclassified_authority_field_fails_the_registry_guard():
    class AuthorityFixture(models.Model):
        imported_grant = models.BooleanField(default=False)

        class Meta:
            app_label = "lane_d_fixture"

    declarations = {
        (AuthorityFixture._meta.label, "id"): NoAuthorityField("Row identity."),
    }
    with pytest.raises(TenantDumpCatalogError, match="field catalog drifted"):
        validate_field_coverage((AuthorityFixture,), declarations)


@isolate_apps()
def test_new_authority_bearing_m2m_is_not_hidden_by_concrete_field_filtering():
    class Grant(models.Model):
        name = models.CharField(max_length=20)

        class Meta:
            app_label = "lane_d_fixture"

    class Principal(models.Model):
        grants = models.ManyToManyField(Grant)

        class Meta:
            app_label = "lane_d_fixture"

    declarations = {
        (Principal._meta.label, "id"): NoAuthorityField("Row identity."),
    }
    with pytest.raises(TenantDumpCatalogError, match="grants"):
        validate_field_coverage((Principal,), declarations)


def test_owner_decision_22_is_an_explicit_preserve_for_every_assignment_field():
    expected = {
        ("machines.MachineOperator", name)
        for name in "id machine user access_level assigned_by assigned_at".split()
    }
    assert expected <= set(AUTHORITY_FIELD_OVERRIDES)
    for edge in expected:
        rule = AUTHORITY_FIELD_OVERRIDES[edge]
        assert rule.dispositions == (AuthorityDisposition.PRESERVE,)
        assert "Owner decision 22" in rule.reason


def test_user_group_and_direct_permission_m2ms_are_explicitly_dropped():
    for field_name in ("groups", "user_permissions"):
        rule = FIELD_POLICIES[("accounts.User", field_name)]
        assert rule.dispositions == (AuthorityDisposition.DROP,)
        assert rule.reason
