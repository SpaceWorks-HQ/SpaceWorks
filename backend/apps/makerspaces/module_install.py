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
from apps.makerspaces.capabilities import prune_features, validate_capabilities
from apps.makerspaces.models import Makerspace
from apps.makerspaces.module_profiles import MINIMAL, profile_modules
from apps.makerspaces.module_registry import (
    BY_KEY,
    MODULES,
    core_module_keys,
    dependents_of,
    module_available,
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
            # False when the owning app is tombstoned. Reported separately from
            # `installed` so a retained-but-unshipped key reads as what it is,
            # rather than looking like the operator never enabled it.
            "available": module_available(definition.key),
            "requires": list(definition.requires_modules),
        }
        for definition in MODULES
    ]


def install_module(makerspace, key, actor=None):
    """Enable `key` and anything it requires. Returns the keys newly added."""
    if key not in BY_KEY:
        raise ModuleInstallError(f"Unknown module {key!r}.")
    # Refused rather than silently accepted: installing a module this deployment does
    # not ship would write the key, report success and change nothing an operator can
    # see. Includes the dependency closure, since pulling in an unavailable
    # requirement produces the same dead capability one step removed.
    unavailable = sorted(k for k in with_dependencies({key}) if not module_available(k))
    if unavailable:
        raise ModuleInstallError(
            f"{', '.join(unavailable)} is not shipped by this deployment "
            "(TOMBSTONED_APPS). Enabling it would have no effect."
        )
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
    # A profile is a convenience list, not a demand: silently skipping what this
    # deployment does not ship is right here, where refusing would make the setup
    # wizard unusable on a tombstoned build.
    keys = {key for key in profile_modules(profile) if module_available(key)}
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
    before_features = sorted(set(locked.enabled_features or []))
    # Drop features whose modules are going away BEFORE validating, or the validation
    # refuses the change outright -- see `prune_features` for why this is a removal
    # rather than an error or a silent keep.
    kept_features, dropped_features = prune_features(locked.enabled_features or [], modules)
    canonical_modules, canonical_features = validate_capabilities(
        sorted(modules), kept_features
    )
    locked.enabled_modules = canonical_modules
    locked.enabled_features = canonical_features
    locked.save(update_fields=["enabled_modules", "enabled_features"])
    if before != canonical_modules or before_features != sorted(canonical_features):
        audit.record(
            actor,
            "makerspace.capabilities_changed",
            makerspace=locked,
            target=locked,
            meta={
                "before": {"modules": before, "features": before_features},
                "after": {"modules": canonical_modules, "features": sorted(canonical_features)},
                # Named explicitly: a feature removed as a consequence of a module going
                # away is the kind of change an operator will otherwise discover only
                # when something stops charging.
                "features_dropped_with_modules": dropped_features,
            },
        )
