"""Install / uninstall / list service for per-makerspace modules.

The single code path behind the management commands. Every mutation locks the
makerspace row, validates through `validate_capabilities` (so the registry's
dependency rules and the core-module requirement are enforced exactly once) and
writes an audit entry.

Uninstalling only clears the capability key -- it never deletes data. The rows
stay, their surfaces stop being served, and reinstalling restores them. That is
what makes uninstall safe enough to not need a destructive-confirmation prompt.
"""

from django.db import transaction

from apps.audit import services as audit
from apps.makerspaces.capabilities import validate_capabilities
from apps.makerspaces.models import Makerspace
from apps.makerspaces.module_profiles import MINIMAL, profile_modules
from apps.makerspaces.module_registry import (
    BY_KEY,
    MODULES,
    core_module_keys,
    dependents_of,
    with_dependencies,
)


class ModuleInstallError(Exception):
    """A module install/uninstall the caller asked for cannot be performed."""


def module_status(makerspace):
    """Every registered module with its state for this makerspace."""
    enabled = set(makerspace.enabled_modules or [])
    core = core_module_keys()
    return [
        {
            "key": definition.key,
            "label": definition.label,
            "description": definition.description,
            "installed": definition.key in enabled or definition.key in core,
            "core": definition.key in core,
            "requires": list(definition.requires_modules),
        }
        for definition in MODULES
    ]


def install_module(makerspace, key, actor=None):
    """Enable `key` and anything it requires. Returns the keys newly added."""
    if key not in BY_KEY:
        raise ModuleInstallError(f"Unknown module {key!r}.")
    with transaction.atomic():
        locked = Makerspace.objects.select_for_update().get(pk=makerspace.pk)
        before = set(locked.enabled_modules or [])
        added = sorted(with_dependencies({key}) - before)
        if not added:
            return []
        _apply(locked, before | set(added), actor)
    makerspace.refresh_from_db(fields=["enabled_modules"])
    return added


def uninstall_module(makerspace, key, actor=None):
    """Disable `key`, keeping its data. Refuses core and depended-on modules."""
    if key not in BY_KEY:
        raise ModuleInstallError(f"Unknown module {key!r}.")
    if key in core_module_keys():
        raise ModuleInstallError(
            f"{key} is a core module and cannot be uninstalled."
        )
    with transaction.atomic():
        locked = Makerspace.objects.select_for_update().get(pk=makerspace.pk)
        before = set(locked.enabled_modules or [])
        if key not in before:
            return []
        blockers = dependents_of(key, before - {key})
        if blockers:
            raise ModuleInstallError(
                f"{key} is required by {', '.join(blockers)}. Uninstall those first."
            )
        _apply(locked, before - {key}, actor)
    makerspace.refresh_from_db(fields=["enabled_modules"])
    return [key]


def apply_profile(makerspace, profile, actor=None):
    """Replace the module set with a named profile. Returns the resulting keys."""
    keys = set(profile_modules(profile))
    with transaction.atomic():
        locked = Makerspace.objects.select_for_update().get(pk=makerspace.pk)
        # Unknown legacy keys are preserved: `_canonical_modules` keeps them and a
        # profile must not silently strip a capability the registry has not learned yet.
        unknown = {key for key in (locked.enabled_modules or []) if key not in BY_KEY}
        # `public_inventory` is core, so the module cannot express "private makerspace".
        # The catalogue switch does: a minimal install publishes nothing until the
        # operator opts in.
        if profile == MINIMAL and locked.public_inventory_enabled:
            locked.public_inventory_enabled = False
            locked.save(update_fields=["public_inventory_enabled"])
        _apply(locked, keys | unknown, actor)
    makerspace.refresh_from_db(fields=["enabled_modules", "public_inventory_enabled"])
    return sorted(keys | unknown)


def _apply(locked, modules, actor):
    before = sorted(set(locked.enabled_modules or []))
    canonical_modules, canonical_features = validate_capabilities(
        sorted(modules), locked.enabled_features or []
    )
    locked.enabled_modules = canonical_modules
    locked.enabled_features = canonical_features
    locked.save(update_fields=["enabled_modules", "enabled_features"])
    if before != canonical_modules:
        audit.record(
            actor,
            "makerspace.capabilities_changed",
            makerspace=locked,
            target=locked,
            meta={"before": {"modules": before}, "after": {"modules": canonical_modules}},
        )
