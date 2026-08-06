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
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover - a broken file fails elsewhere
            continue
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
                if not (
                    isinstance(node.value, ast.Constant)
                    and isinstance(node.value.value, str)
                ):
                    continue
                if any(
                    isinstance(target, ast.Name) and target.id == "MODULE_KEY"
                    for target in node.targets
                ):
                    keys.add(node.value.value)
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


def test_derived_defaults_and_workflows_are_unchanged():
    assert DEFAULT_ENABLED_MODULES == LEGACY_DEFAULT_ENABLED_MODULES
    assert default_enabled_modules() == LEGACY_DEFAULT_ENABLED_MODULES
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


def test_core_modules_match_the_approved_split_and_are_default_on():
    assert module_registry.core_module_keys() == APPROVED_CORE
    for definition in module_registry.MODULES:
        if definition.is_core:
            assert definition.default_enabled


def test_registry_is_internally_consistent():
    assert len(module_registry.MODULES) == 24
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
