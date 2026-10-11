import secrets

import pytest
from django.apps import apps
from django.db import models
from django.test.utils import isolate_apps
from django.utils import timezone

from apps.integrations.models_recipients import NotificationRecipientKind
from apps.tenant_migration.projection_guards import (
    DECLARED_UNIQUE_CONSTRAINT_RISKS,
    ProjectionRegistryError,
    non_null_role_dependents,
    validate_notification_recipient_kinds,
    validate_projection_fk_registry,
    validate_projection_registry,
    validate_unique_constraint_risks,
)
from apps.tenant_migration.row_dispositions import row_disposition
from apps.tenant_migration.unique_values import (
    DEPLOYMENT_GLOBAL_UNIQUE_RULES,
    UniqueValueDisposition,
)
from apps.tenant_migration.target_projection import (
    DROPPED_NOTIFICATION_RECIPIENT_KINDS,
    FK_POLICIES,
    ROW_POLICIES,
    SEEDED_RESOLUTIONS,
    TARGET_FIELD_PROJECTION,
    ReferenceDisposition,
    RowDisposition,
)


from .target_projection_expectations import EXPECTED_TARGET_VALUES


@pytest.mark.parametrize("edge, expected", EXPECTED_TARGET_VALUES.items())
def test_each_target_owned_projection_value(edge, expected, monkeypatch):
    policy = TARGET_FIELD_PROJECTION[edge]
    if expected is secrets.token_hex:
        # Model defaults must generate fresh target codes, never preserve source ones.
        assert policy.use_model_default
        assert apps.get_model(edge[0])._meta.get_field(edge[1]).default is secrets.token_hex
        monkeypatch.setattr(secrets, "token_bytes", lambda nbytes=None: b"\x42" * (nbytes or 32))
        assert policy.resolved_value(*edge) == "42" * 32
    elif expected is timezone.now:
        assert policy.resolver is timezone.now
        started = timezone.now()
        assert started <= policy.resolved_value(*edge) <= timezone.now()
    else:
        assert policy.resolved_value(*edge) == expected
    assert policy.reason


def test_expected_values_cover_the_complete_projection():
    assert set(EXPECTED_TARGET_VALUES) == set(TARGET_FIELD_PROJECTION)


def test_only_operator_selectable_policy_fields_allow_an_override():
    allowed = {
        ("makerspaces.MakerspaceMembershipSettings", "join_mode"),
        ("makerspaces.Makerspace", "membership_policy"),
        ("makerspaces.Makerspace", "referrals_enabled"),
        ("makerspaces.Makerspace", "enabled_modules"),
        ("makerspaces.Makerspace", "enabled_features"),
    }
    assert {
        edge for edge, policy in TARGET_FIELD_PROJECTION.items()
        if policy.allow_superadmin_override
    } == allowed


def test_authority_rows_follow_the_explicit_drop_or_decision_22_policy():
    expected_dropped = {
        "machines.RoleMachineScope",
        "machines.RoleMachineTypeScope",
        "integrations.NotificationRecipient",
        "integrations.RecipientMachineTypeScope",
        "integrations.RecipientMachineScope",
        "integrations.RecipientCategoryScope",
        "makerspaces.MembershipRequest",
    }
    assert all(
        ROW_POLICIES[label].disposition is RowDisposition.DROP
        for label in expected_dropped
    )
    assert (
        ROW_POLICIES["makerspaces.MakerspaceRole"].disposition
        is RowDisposition.KEEP_TARGET
    )
    assert (
        ROW_POLICIES["machines.MachineOperator"].disposition
        is RowDisposition.PRESERVE_LIVE
    )
    assert "Owner decision 22" in ROW_POLICIES["machines.MachineOperator"].reason
    assert row_disposition("machines.MachineOperator", {}, None) == "insert"
    assert ROW_POLICIES["makerspaces.Station"].disposition is RowDisposition.STAGE_INERT


def test_only_open_membership_request_states_are_authority_rows():
    policy = ROW_POLICIES["makerspaces.MembershipRequest"]
    assert policy.condition == ("state", frozenset({"requested", "invited", "awaiting_vouches"}))
    assert row_disposition("makerspaces.MembershipRequest", {"state": "awaiting_vouches"}, None) == "drop"


def test_every_notification_recipient_kind_is_declared_dropped():
    assert DROPPED_NOTIFICATION_RECIPIENT_KINDS == set(NotificationRecipientKind.values)
    assert (
        ROW_POLICIES["integrations.NotificationRecipient"].disposition
        is RowDisposition.DROP
    )


def test_telegram_destinations_are_staged_inactive():
    policy = TARGET_FIELD_PROJECTION[("integrations.NotificationDestination", "is_active")]
    row_policy = ROW_POLICIES["integrations.NotificationDestination"]
    assert policy.condition == ("channel", "telegram")
    assert policy.resolved_value("integrations.NotificationDestination", "is_active") is False
    assert row_policy.disposition is RowDisposition.STAGE_INERT
    assert row_policy.condition == ("channel", "telegram")


def test_category_resolution_retains_archived_tenant_edits():
    resolution = SEEDED_RESOLUTIONS["inventory.Category"]
    archived = {
        "slug": "sensors",
        "name": "Lab Sensors",
        "display_order": 41,
        "icon": "radar",
        "loan_days": 14,
        "max_renewals": 0,
        "created_at": "source-created",
        "updated_at": "source-updated",
    }
    assert resolution.lookup_fields == ("slug",)
    assert resolution.archived_updates(archived) == {
        "name": "Lab Sensors",
        "display_order": 41,
        "icon": "radar",
        "loan_days": 14,
        "max_renewals": 0,
        "created_at": "source-created",
        "updated_at": "source-updated",
    }


def test_global_machine_type_resolution_requires_definition_fingerprint():
    resolution = SEEDED_RESOLUTIONS["machines.MachineType"]
    assert resolution.lookup_fields == ("slug",)
    assert set(resolution.definition_fingerprint_fields) == {
        "name", "icon", "is_builtin", "managing_action", "capability_config"
    }


def test_roles_are_never_remapped_into_live_scope_or_recipient_rows():
    assert (
        FK_POLICIES[
            ("makerspaces.MakerspaceMembership", "assigned_role")
        ].disposition
        is ReferenceDisposition.REMAP_TARGET_MEMBER
    )
    assert (
        FK_POLICIES[("makerspaces.MembershipRequest", "assigned_role")].disposition
        is ReferenceDisposition.REMAP_TARGET_MEMBER
    )
    for edge in (
        ("machines.RoleMachineScope", "role"),
        ("machines.RoleMachineTypeScope", "role"),
        ("integrations.NotificationRecipient", "role"),
    ):
        assert FK_POLICIES[edge].disposition is ReferenceDisposition.DROP_ROW


def test_complete_projection_registry_is_valid():
    validate_projection_registry()


def test_deployment_global_uniqueness_risks_are_explicitly_disposed():
    assert {
        (risk.model_label, risk.constraint_name)
        for risk in DECLARED_UNIQUE_CONSTRAINT_RISKS
    } >= {
        ("boxes.Box", "field:code"),
        ("boxes.QrCode", "field:payload"),
        ("evidence.EvidencePhoto", "field:object_key"),
        ("events.EventStationBinding", "field:station"),
        ("machines.MachineType", "uniq_global_machinetype_slug"),
    }
    assert all(policy.reason for policy in DEPLOYMENT_GLOBAL_UNIQUE_RULES.values())
    assert (
        DEPLOYMENT_GLOBAL_UNIQUE_RULES[("boxes.QrCode", "field:payload")].disposition
        is UniqueValueDisposition.PRESERVE_OR_REGENERATE
    )
    assert (
        DEPLOYMENT_GLOBAL_UNIQUE_RULES[
            ("events.EventStationBinding", "field:station")
        ].disposition
        is UniqueValueDisposition.REMAPPED_REFERENCE
    )


def test_every_non_null_dropped_role_dependent_has_a_disposition():
    for edge in non_null_role_dependents():
        assert FK_POLICIES[edge].disposition in {
            ReferenceDisposition.DROP_ROW,
            ReferenceDisposition.REMAP_TARGET_MEMBER,
        }


def test_fk_guard_fails_when_one_declaration_is_removed():
    changed = dict(FK_POLICIES)
    changed.pop(next(iter(changed)))
    with pytest.raises(ProjectionRegistryError, match="projection FK registry drifted"):
        validate_projection_fk_registry(changed)


def test_uniqueness_guard_fails_when_one_declaration_is_removed():
    changed = dict(DEPLOYMENT_GLOBAL_UNIQUE_RULES)
    changed.pop(next(iter(changed)))
    with pytest.raises(ProjectionRegistryError, match="uniqueness registry drifted"):
        validate_unique_constraint_risks(changed)


@isolate_apps()
def test_uniqueness_guard_fails_for_undeclared_fixture_unique_column():
    class ExportFixture(models.Model):
        makerspace = models.IntegerField()
        imported_key = models.CharField(max_length=32, unique=True)

        class Meta:
            app_label = "fixture"

    with pytest.raises(
        ProjectionRegistryError,
        match=r"missing=.*fixture.ExportFixture.*field:imported_key",
    ):
        validate_unique_constraint_risks(
            {},
            exported_models=(ExportFixture,),
            ownership_paths={"fixture.ExportFixture": ("makerspace",)},
        )


def test_recipient_kind_guard_fails_when_one_declaration_is_removed():
    changed = set(DROPPED_NOTIFICATION_RECIPIENT_KINDS)
    changed.remove(NotificationRecipientKind.USER)
    with pytest.raises(ProjectionRegistryError, match="recipient kind registry drifted"):
        validate_notification_recipient_kinds(changed)
