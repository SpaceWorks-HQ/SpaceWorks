"""Drift guards for the module registry (plan A11).

The registry is now the single source of truth for module keys. These tests make it
impossible to (a) register a module nothing enforces, (b) enforce a key nobody
registered, or (c) change the derived lists and payloads without noticing.
"""

import ast
from pathlib import Path

import pytest

import apps.makerspaces
from apps.makerspaces import module_registry
from apps.makerspaces.capabilities import FEATURE_DEFINITIONS, FEATURE_MODULES
from apps.makerspaces.models import DEFAULT_ENABLED_MODULES, default_enabled_modules
from apps.makerspaces.platform import MODULE_WORKFLOWS

APPS_DIR = Path(apps.makerspaces.__file__).resolve().parent.parent
GUARD_CALLS = {"module_enabled", "require_module"}

# Everything the registry replaced, captured verbatim from before the refactor.
# Phase 1 is a pure derivation change, so these must still come out identical.
LEGACY_DEFAULT_ENABLED_MODULES = [
    "public_inventory", "request_workflow", "staff_admin", "guest_handover", "scanner",
    "printing", "telegram", "evidence_uploads", "qr_management", "bulk_import",
    "containers", "stock_transfers", "stocktake", "reports", "qr_print_batches",
    "asset_units", "procurement", "machines", "machine_service", "events", "bookings",
    "maintenance", "membership",
]
LEGACY_MODULE_WORKFLOWS = {
    "public_inventory": ["catalog"],
    "request_workflow": ["request_submit", "request_status"],
    "staff_admin": ["staff_inventory", "staff_requests"],
    "guest_handover": ["guest_issue", "guest_return"],
    "scanner": ["qr_scan", "container_lookup"],
    "qr_management": ["qr_generate", "qr_revoke", "qr_print"],
    "bulk_import": ["bulk_import"],
    "containers": ["container_lookup", "container_move"],
    "stock_transfers": ["stock_transfer"],
    "stocktake": ["stocktake"],
    "reports": ["analytics", "report_export"],
    "qr_print_batches": ["qr_print_batch"],
    "asset_units": ["asset_qr_generation"],
    "printing": ["printing_requests"],
    "machine_service": ["machine_service_requests"],
    "telegram": ["telegram_alerts"],
    "maintenance": ["maintenance"],
    "procurement": ["procurement"],
    "evidence_uploads": ["evidence_uploads"],
}
# Owner-approved core set (plan 3.3). The Hard Rules require a box QR scan AND an
# issue photo to hand hardware over, so evidence/QR/scanner cannot be optional.
APPROVED_CORE = {
    "public_inventory", "request_workflow", "staff_admin",
    "evidence_uploads", "qr_management", "scanner",
}


def _guarded_module_keys():
    """Every module key a guard call or MODULE_KEY constant actually references.

    Parsed rather than grepped because several call sites wrap their arguments over
    multiple lines, which a line-oriented regex silently misses.
    """
    keys = set()
    for path in APPS_DIR.rglob("*.py"):
        if "migrations" in path.parts:
            continue
        # utf-8-sig, and a HARD failure on an unparseable file. Both matter: a leading
        # UTF-8 BOM makes ast.parse raise SyntaxError, and skipping the file made this
        # guard silently blind to every module gate inside it -- eighteen files in
        # `apps/` carried one, so "no call site references this key" could mean the
        # guard simply never read the file that does.
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
                if name in GUARD_CALLS:
                    keys.update(
                        argument.value
                        for argument in node.args
                        if isinstance(argument, ast.Constant) and isinstance(argument.value, str)
                    )
            elif isinstance(node, ast.Assign):
                names = {
                    target.id for target in node.targets if isinstance(target, ast.Name)
                }
                if (
                    isinstance(node.value, ast.Constant)
                    and isinstance(node.value.value, str)
                    and "MODULE_KEY" in names
                ):
                    keys.add(node.value.value)
                # A guard may also be mapping-driven: one `module_enabled(ms, key)` call
                # fed by a declared table, rather than one literal call per key. The
                # notification channels do this (`CHANNEL_MODULE_KEYS`) because the five
                # channels share a single gate. The table's values ARE the enforcement
                # declaration, so they count -- otherwise the only way to satisfy this
                # guard would be to un-DRY the gate into five identical branches.
                elif isinstance(node.value, ast.Dict) and any(
                    name.endswith("MODULE_KEYS") for name in names
                ):
                    keys.update(
                        value.value
                        for value in node.value.values
                        if isinstance(value, ast.Constant) and isinstance(value.value, str)
                    )
    return keys


def test_every_registered_module_is_enforced_as_declared():
    guarded = _guarded_module_keys()
    feature_parents = {
        module
        for definition in FEATURE_DEFINITIONS
        for module in (definition.parent_module, *definition.requires_modules)
        if module
    }
    for definition in module_registry.MODULES:
        if definition.enforcement == module_registry.GUARD:
            assert definition.key in guarded, (
                f"{definition.key} declares guard enforcement but no module_enabled/"
                f"require_module call site references it."
            )
        elif definition.enforcement == module_registry.FEATURE_PARENT:
            assert definition.key in feature_parents, (
                f"{definition.key} declares feature-parent enforcement but no feature "
                f"depends on it."
            )
        else:
            assert definition.description, (
                f"{definition.key} is unenforced and must justify that in its description."
            )


def test_every_enforced_module_key_is_registered():
    # A guard on an unregistered key is dead: `module_enabled` returns False forever
    # because nothing can ever put the key on a makerspace through the registry.
    unregistered = _guarded_module_keys() - module_registry.MODULE_KEYS
    assert unregistered == set(), f"Guarded but unregistered module keys: {sorted(unregistered)}."


def test_modules_are_opt_in_and_a_new_makerspace_gets_core_only():
    # Modules default off (plan D4). The pre-opt-in set survives intact as the
    # `everything` profile, so nothing was dropped -- only the default changed.
    # `POST_LEGACY_KEYS` is the deliberate growth since that baseline; a key added to the
    # registry without being listed here fails this test, which is the point.
    from apps.makerspaces.module_profiles import EVERYTHING, profile_modules

    # `slack`/`mattermost`/`discord` are the per-channel notification module keys. The
    # first two were previously ungated (webhook presence alone decided), which is why
    # makerspaces/0056 backfills them onto existing rows; `discord` is genuinely new and
    # stays opt-in.
    POST_LEGACY_KEYS = {
        "notifications", "email", "slack", "mattermost", "discord",
    }

    # Four keys deliberately default ON, and are the only ones allowed to. They are not
    # capabilities being offered -- they are switches placed in front of substrate that
    # was previously unconditional, so defaulting them off would remove working surfaces
    # from a makerspace that never asked for a change. Anything else defaulting on is
    # drift and fails here.
    DEFAULT_ON_KEYS = {"payments", "accounts", "mobile", "updates"}

    assert set(DEFAULT_ENABLED_MODULES) == module_registry.core_module_keys() | DEFAULT_ON_KEYS
    assert default_enabled_modules() == DEFAULT_ENABLED_MODULES
    assert {
        definition.key for definition in module_registry.MODULES if definition.default_enabled
    } == DEFAULT_ON_KEYS
    assert (
        set(profile_modules(EVERYTHING))
        == set(LEGACY_DEFAULT_ENABLED_MODULES) | POST_LEGACY_KEYS | DEFAULT_ON_KEYS
    )


def test_derived_workflows_are_unchanged():
    assert MODULE_WORKFLOWS == LEGACY_MODULE_WORKFLOWS


def test_default_callable_returns_a_fresh_list_each_call():
    # It backs a JSONField default. Handing out a shared list would let one
    # makerspace's stored row mutate the default for every makerspace created after it.
    first = default_enabled_modules()
    first.append("tampered")
    assert "tampered" not in default_enabled_modules()
    assert "tampered" not in module_registry.default_enabled_module_keys()


@pytest.mark.parametrize(
    "dotted_path",
    [
        # Referenced by existing migrations; these import paths must keep resolving
        # or `migrate` breaks on a fresh database.
        "apps.makerspaces.models.default_enabled_modules",
        "apps.makerspaces.capabilities.default_enabled_features",
        "apps.makerspaces.models.generate_publishable_key",
        "apps.makerspaces.models.generate_public_code",
        "apps.makerspaces.models.default_branding_config",
        "apps.makerspaces.models.default_theme_config",
        "apps.makerspaces.models.generate_domain_verification_token",
        "apps.makerspaces.validators.validate_google_maps_url",
        "apps.makerspaces.validators.validate_presence_presets",
    ],
)
def test_migration_referenced_callables_still_resolve(dotted_path):
    from importlib import import_module

    module_path, _, attribute = dotted_path.rpartition(".")
    assert callable(getattr(import_module(module_path), attribute))


def test_core_modules_match_the_approved_split_and_are_always_installed():
    assert module_registry.core_module_keys() == APPROVED_CORE
    installed_by_default = set(default_enabled_modules())
    for definition in module_registry.MODULES:
        if definition.is_core:
            # Core is on by definition, so it must not also claim default_enabled --
            # two sources for one fact is exactly the drift this registry removes.
            assert not definition.default_enabled
            assert definition.key in installed_by_default


def test_registry_is_internally_consistent():
    # 24 at the registry's introduction, plus `email` (plan A5), plus the three
    # per-channel notification keys `slack`/`mattermost`/`discord`, plus the four
    # phase-3 keys placed in front of previously ungated substrate: `payments`,
    # `accounts`, `mobile` and `updates`.
    assert len(module_registry.MODULES) == 32
    assert len(module_registry.BY_KEY) == len(module_registry.MODULES)
    for definition in module_registry.MODULES:
        assert definition.label and definition.description and definition.app_label
        for required in definition.requires_modules:
            assert required in module_registry.BY_KEY
    # Feature parents resolve against the registry, so the two layers cannot drift.
    assert FEATURE_MODULES == module_registry.MODULE_KEYS
    for definition in FEATURE_DEFINITIONS:
        for module in (definition.parent_module, *definition.requires_modules):
            assert module is None or module in module_registry.MODULE_KEYS


def test_unexposed_modules_never_reach_the_frontend():
    # The bootstrap payload is byte-for-byte load-bearing: an internal master switch
    # must not leak into `modules` or `workflows`. No module is unexposed yet, so this
    # asserts the mechanism rather than a current exclusion.
    hidden = {
        definition.key for definition in module_registry.MODULES if not definition.frontend_exposed
    }
    assert hidden & set(MODULE_WORKFLOWS) == set()
    for key in hidden:
        assert module_registry.is_frontend_exposed(key) is False
    # Unknown legacy keys stay exposed -- `_canonical_modules` preserves them and
    # dropping them here would silently strip a tenant's stored capability.
    assert module_registry.is_frontend_exposed("legacy_unknown_key") is True


def test_printing_dependency_is_registry_data_not_a_hardcoded_branch():
    assert module_registry.module_dependencies()["printing"] == ("machine_service",)


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

    assert "accounts" not in dependencies.get("membership", ())
    assert dependencies["mobile"] == ("accounts",)
    assert "accounts" not in dependencies


def test_events_and_bookings_do_not_require_member_accounts():
    # The lean install is Inventory + Machines with the space's own login, and events,
    # bookings and machine service must all keep working there. Only the native-device
    # layer depends on built-in member accounts.
    dependencies = module_registry.module_dependencies()

    for key in ("events", "bookings", "machines", "machine_service", "membership", "payments", "reports"):
        assert "accounts" not in dependencies.get(key, ())


def test_payments_features_require_both_the_domain_and_the_payments_module():
    # Re-parenting the domain features onto `payments` outright would have lost a real
    # constraint -- charging for bookings must still require the bookings module -- so
    # `payments` is an added requirement rather than a replaced parent.
    by_key = {definition.key: definition for definition in FEATURE_DEFINITIONS}

    assert by_key["payments.bookings"].parent_module == "bookings"
    for key in ("payments.machines", "payments.bookings", "payments.events", "payments.membership"):
        assert "payments" in by_key[key].requires_modules
    assert by_key["payments.enabled"].parent_module == "payments"
    assert by_key["mobile.push"].parent_module == "mobile"
