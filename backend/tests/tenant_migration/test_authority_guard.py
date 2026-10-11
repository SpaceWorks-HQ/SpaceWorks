import pytest

from apps.tenant_migration.authority_guards import (
    DECLARED_AUTHORITY_FIELDS,
    AuthorityRegistryError,
    discover_exported_authority_fields,
    validate_authority_registry,
)


def test_complete_authority_registry_is_valid():
    validate_authority_registry()


def test_every_replay_field_has_an_explicit_drop_override():
    from apps.tenant_migration.tenant_dump_authority import AUTHORITY_FIELD_OVERRIDES
    from apps.tenant_migration.tenant_dump_field_snapshot import FIRST_PARTY_FIELD_NAMES
    from apps.tenant_migration.tenant_dump_types import AuthorityDisposition
    label = "hardware_requests.ReplayCommand"
    for name in FIRST_PARTY_FIELD_NAMES[label]:
        assert AUTHORITY_FIELD_OVERRIDES[(label, name)].dispositions == (AuthorityDisposition.DROP,)


def test_mechanically_discovered_authority_inputs_are_explicit():
    assert discover_exported_authority_fields() <= set(DECLARED_AUTHORITY_FIELDS)


def test_locked_role_authority_modules_remain_in_the_scan():
    from apps.tenant_migration.authority_guards import APPS_DIR, AUTHORIZATION_SOURCES

    assert {
        APPS_DIR / "makerspaces" / "role_authority.py",
        APPS_DIR / "makerspaces" / "role_assignments.py",
    } <= set(AUTHORIZATION_SOURCES)


def test_declared_relational_and_discriminator_authority_inputs():
    required = {
        ("makerspaces.MakerspaceMembership", "role"),
        ("makerspaces.MakerspaceMembership", "assigned_role"),
        ("makerspaces.MakerspaceMembership", "status"),
        ("makerspaces.MakerspaceMembership", "can_verify"),
        ("makerspaces.MakerspaceMembership", "can_refer"),
        ("makerspaces.MakerspaceRole", "granted_actions"),
        ("makerspaces.MakerspaceRole", "slug"),
        ("makerspaces.Makerspace", "slug"),
        ("makerspaces.Makerspace", "public_inventory_enabled"),
        ("machines.MachineType", "slug"),
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
        ("makerspaces.Station", "created_by"),
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


@pytest.mark.parametrize("label", ["makerspaces.Makerspace", "machines.MachineType"])
def test_routing_identifier_authority_must_remain_declared(label):
    changed = dict(DECLARED_AUTHORITY_FIELDS)
    changed.pop((label, "slug"))
    with pytest.raises(AuthorityRegistryError, match="authorization inputs are undeclared"):
        validate_authority_registry(changed, required_fields=())
