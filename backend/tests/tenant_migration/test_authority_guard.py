import pytest

from apps.tenant_migration.authority_guards import (
    DECLARED_AUTHORITY_FIELDS,
    AuthorityRegistryError,
    discover_exported_authority_fields,
    validate_authority_registry,
)


def test_complete_authority_registry_is_valid():
    validate_authority_registry()


def test_mechanically_discovered_authority_inputs_are_explicit():
    assert discover_exported_authority_fields() <= set(DECLARED_AUTHORITY_FIELDS)


def test_declared_relational_and_discriminator_authority_inputs():
    required = {
        ("makerspaces.MakerspaceMembership", "role"),
        ("makerspaces.MakerspaceMembership", "assigned_role"),
        ("makerspaces.MakerspaceMembership", "status"),
        ("makerspaces.MakerspaceMembership", "can_verify"),
        ("makerspaces.MakerspaceMembership", "can_refer"),
        ("makerspaces.MakerspaceRole", "granted_actions"),
        ("makerspaces.MakerspaceRole", "slug"),
        ("makerspaces.MakerspaceRole", "is_default"),
        ("makerspaces.MakerspaceRole", "is_protected"),
        ("machines.MachineType", "managing_action"),
        ("machines.MachineOperator", "access_level"),
        ("machines.MachineOperator", "assigned_by"),
        ("machines.MachineOperator", "assigned_at"),
        ("machines.RoleMachineScope", "role"),
        ("machines.RoleMachineTypeScope", "role"),
        ("integrations.NotificationRecipient", "kind"),
        ("integrations.NotificationRecipient", "role"),
        ("integrations.NotificationRecipient", "user"),
        ("makerspaces.MembershipRequest", "assigned_role"),
        ("makerspaces.MembershipRequest", "auto_activate_on_claim"),
    }
    assert required <= set(DECLARED_AUTHORITY_FIELDS)


def test_authority_guard_fails_when_a_discovered_declaration_is_removed():
    changed = dict(DECLARED_AUTHORITY_FIELDS)
    changed.pop(("machines.MachineType", "managing_action"))
    with pytest.raises(AuthorityRegistryError, match="authorization inputs are undeclared"):
        validate_authority_registry(changed, required_fields=())


def test_authority_guard_fails_when_an_explicit_declaration_is_removed():
    changed = dict(DECLARED_AUTHORITY_FIELDS)
    changed.pop(("makerspaces.MakerspaceMembership", "can_verify"))
    with pytest.raises(AuthorityRegistryError, match="required authority declarations"):
        validate_authority_registry(changed)
