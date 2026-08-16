import pytest

from apps.integrations.models_recipients import NotificationRecipientKind
from apps.makerspaces.capabilities import default_enabled_features
from apps.makerspaces.models import (
    Makerspace,
    MakerspaceMembership,
    default_enabled_modules,
)
from apps.tenant_migration.projection_guards import (
    DECLARED_UNIQUE_CONSTRAINT_RISKS,
    ProjectionRegistryError,
    non_null_role_dependents,
    validate_notification_recipient_kinds,
    validate_projection_fk_registry,
    validate_projection_registry,
    validate_unique_constraint_risks,
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


EXPECTED_TARGET_VALUES = {
    ("makerspaces.Makerspace", "frontend_domain"): None,
    ("makerspaces.Makerspace", "frontend_domain_status"): Makerspace.DomainStatus.PENDING,
    ("makerspaces.Makerspace", "domain_verified_at"): None,
    ("makerspaces.Makerspace", "frontend_domain_changed_at"): None,
    ("makerspaces.Makerspace", "hidden_from_central_directory"): False,
    ("makerspaces.Makerspace", "superadmin_access_enabled"): True,
    ("makerspaces.Makerspace", "archived_at"): None,
    ("makerspaces.Makerspace", "resource_limit_overrides"): {},
    ("makerspaces.Makerspace", "membership_policy"): Makerspace.MembershipPolicy.REQUEST,
    ("makerspaces.Makerspace", "referrals_enabled"): False,
    ("makerspaces.Makerspace", "telegram_group_chat_id"): "",
    ("makerspaces.Makerspace", "smtp_host"): "",
    ("makerspaces.Makerspace", "smtp_port"): 587,
    ("makerspaces.Makerspace", "smtp_username"): "",
    ("makerspaces.Makerspace", "smtp_use_tls"): True,
    ("makerspaces.Makerspace", "smtp_use_ssl"): False,
    ("makerspaces.Makerspace", "enabled_modules"): default_enabled_modules(),
    ("makerspaces.Makerspace", "enabled_features"): default_enabled_features(),
    ("makerspaces.MakerspaceMembership", "receives_notifications"): True,
    ("makerspaces.MakerspaceMembership", "role"): MakerspaceMembership.Role.CUSTOM,
    ("makerspaces.MakerspaceMembership", "can_refer"): True,
    ("makerspaces.MakerspaceMembership", "can_verify"): False,
    ("makerspaces.MembershipRequest", "auto_activate_on_claim"): False,
    ("machines.MachineType", "managing_action"): "",
    ("integrations.NotificationDestination", "is_active"): False,
}


@pytest.mark.parametrize("edge, expected", EXPECTED_TARGET_VALUES.items())
def test_each_target_owned_projection_value(edge, expected):
    policy = TARGET_FIELD_PROJECTION[edge]
    assert policy.resolved_value(*edge) == expected
    assert policy.reason


def test_expected_values_cover_the_complete_projection():
    assert set(EXPECTED_TARGET_VALUES) == set(TARGET_FIELD_PROJECTION)


def test_only_operator_selectable_policy_fields_allow_an_override():
    allowed = {
        ("makerspaces.Makerspace", "membership_policy"),
        ("makerspaces.Makerspace", "referrals_enabled"),
        ("makerspaces.Makerspace", "enabled_modules"),
        ("makerspaces.Makerspace", "enabled_features"),
    }
    assert {
        edge for edge, policy in TARGET_FIELD_PROJECTION.items()
        if policy.allow_superadmin_override
    } == allowed


def test_authority_and_disclosure_rows_cannot_arrive_live():
    expected_dropped = {
        "machines.MachineOperator",
        "machines.RoleMachineScope",
        "machines.RoleMachineTypeScope",
        "integrations.NotificationRecipient",
        "integrations.RecipientMachineTypeScope",
        "integrations.RecipientMachineScope",
        "integrations.RecipientCategoryScope",
    }
    assert all(
        ROW_POLICIES[label].disposition is RowDisposition.DROP
        for label in expected_dropped
    )
    assert (
        ROW_POLICIES["makerspaces.MakerspaceRole"].disposition
        is RowDisposition.KEEP_TARGET
    )


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
        "created_at": "source-created",
        "updated_at": "source-updated",
    }
    assert resolution.lookup_fields == ("slug",)
    assert resolution.archived_updates(archived) == {
        "name": "Lab Sensors",
        "display_order": 41,
        "icon": "radar",
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


def test_uniqueness_risks_are_introspected_for_resolved_and_seeded_rows():
    assert {
        (risk.model_label, risk.constraint_name)
        for risk in DECLARED_UNIQUE_CONSTRAINT_RISKS
    } >= {
        ("inventory.Category", "uniq_category_slug_per_makerspace"),
        ("machines.MachineType", "uniq_global_machinetype_slug"),
        ("machines.RoleMachineTypeScope", "rolemachinetypescope_uniq"),
    }


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
    changed = set(DECLARED_UNIQUE_CONSTRAINT_RISKS)
    changed.pop()
    with pytest.raises(ProjectionRegistryError, match="uniqueness registry drifted"):
        validate_unique_constraint_risks(changed)


def test_recipient_kind_guard_fails_when_one_declaration_is_removed():
    changed = set(DROPPED_NOTIFICATION_RECIPIENT_KINDS)
    changed.remove(NotificationRecipientKind.USER)
    with pytest.raises(ProjectionRegistryError, match="recipient kind registry drifted"):
        validate_notification_recipient_kinds(changed)
