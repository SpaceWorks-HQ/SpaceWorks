"""Group and dependency drift guards for the makerspace module registry."""

import pytest

from apps.makerspaces import module_registry
from apps.makerspaces.capabilities import FEATURE_DEFINITIONS


def test_every_module_declares_a_known_group():
    # A module with no group would vanish from the console it is administered from, so
    # `group` has no default and the registry refuses to import without it.
    for definition in module_registry.MODULES:
        assert definition.group in module_registry.GROUP_KEYS


def test_a_module_without_a_group_is_rejected():
    with pytest.raises(TypeError):
        module_registry.ModuleDefinition(
            "ungrouped", "Ungrouped", "No group declared.", "operations", module_registry.GUARD,
        )


def test_an_unknown_group_is_rejected_at_import(monkeypatch):
    bogus = module_registry.ModuleDefinition(
        "bogus", "Bogus", "Names a group that does not exist.", "operations",
        module_registry.GUARD, group="not_a_group",
    )
    broken = (*module_registry.MODULES, bogus)
    monkeypatch.setattr(module_registry, "MODULES", broken)
    monkeypatch.setattr(module_registry, "BY_KEY", {d.key: d for d in broken})

    with pytest.raises(module_registry.ImproperlyConfiguredRegistry, match="not_a_group"):
        module_registry._validate_registry()


def test_an_empty_group_is_rejected_at_import(monkeypatch):
    # A heading with nothing behind it reads as a broken install, not an unused one.
    orphan = module_registry.GroupDefinition("orphan", "Orphan", "Holds no modules.")
    # Computed once: reading module_registry.GROUPS again after the first setattr would
    # splat the already-patched tuple and add `orphan` twice.
    groups = (*module_registry.GROUPS, orphan)
    monkeypatch.setattr(module_registry, "GROUPS", groups)
    monkeypatch.setattr(module_registry, "GROUPS_BY_KEY", {g.key: g for g in groups})

    with pytest.raises(module_registry.ImproperlyConfiguredRegistry, match="contains no modules"):
        module_registry._validate_registry()


def test_groups_partition_every_module_key():
    grouped = module_registry.modules_by_group()

    # Every group is present even before any module claims it, and no key is orphaned.
    assert set(grouped) == set(module_registry.GROUP_KEYS)
    covered = {definition.key for definitions in grouped.values() for definition in definitions}
    assert covered == set(module_registry.MODULE_KEYS)
    # No key appears twice: `group` is a single field, so a duplicate would mean the
    # console rendered one switch under two headings that disagree.
    total = sum(len(definitions) for definitions in grouped.values())
    assert total == len(module_registry.MODULES)


def test_a_group_holding_a_core_module_can_never_be_switched_off():
    # `_canonical_modules` adds core back on every write, so a master toggle offering
    # "off" for such a group would be a control whose effect is silently undone.
    for group in module_registry.GROUPS:
        keys = module_registry.group_module_keys(group.key)
        holds_core = any(module_registry.BY_KEY[key].is_core for key in keys)
        assert module_registry.group_is_always_on(group.key) == (holds_core or group.always_on)
    assert module_registry.group_is_always_on(module_registry.GROUP_INVENTORY) is True
    assert module_registry.group_is_always_on(module_registry.GROUP_EVENTS) is False


def test_group_lookup_tolerates_an_unknown_legacy_key():
    # `_canonical_modules` preserves unknown keys, so filing one under an invented group
    # would misrepresent a tenant's stored capability.
    assert module_registry.group_for("legacy_unknown_key") is None
    assert module_registry.group_for("events") == module_registry.GROUP_EVENTS


def test_only_mobile_requires_member_accounts():
    # Community enrolment may use external OIDC while built-in account self-service is
    # off. A native device grant still binds to a built-in member account.
    dependencies = module_registry.module_dependencies()

    assert "member_accounts" not in dependencies.get("membership", ())
    assert dependencies["mobile"] == ("member_accounts",)
    assert "member_accounts" not in dependencies


def test_events_and_bookings_do_not_require_member_accounts():
    # The lean install is Inventory + Machines with the space's own login, and events,
    # bookings and machine service must all keep working there. Only the native-device
    # layer depends on built-in member accounts.
    dependencies = module_registry.module_dependencies()

    keys = ("events", "bookings", "machines", "machine_service", "membership", "payments", "reports")
    for key in keys:
        assert "member_accounts" not in dependencies.get(key, ())


def test_payments_features_require_both_the_domain_and_the_payments_module():
    # Re-parenting the domain features onto `payments` outright would have lost a real
    # constraint -- charging for bookings must still require the bookings module -- so
    # `payments` is an added requirement rather than a replaced parent.
    by_key = {definition.key: definition for definition in FEATURE_DEFINITIONS}

    assert by_key["payments.bookings"].parent_module == "bookings"
    keys = ("payments.machines", "payments.bookings", "payments.events", "payments.membership")
    for key in keys:
        assert "payments" in by_key[key].requires_modules
    assert by_key["payments.enabled"].parent_module == "payments"
    assert by_key["mobile.push"].parent_module == "mobile"
