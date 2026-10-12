"""Capability normalization, dependencies and feature pruning."""
from django.core.exceptions import ValidationError
from .module_registry import BY_KEY, core_module_keys, module_dependencies
from .capability_definitions import FEATURE_DEFINITIONS, FEATURES, FEATURE_MODULES


def default_enabled_features():
    """Return the enabled-by-default features for a new makerspace."""
    return [definition.key for definition in FEATURE_DEFINITIONS if definition.default_enabled]


def feature_required_modules(key):
    """Every module a feature needs: its parent plus anything it declares."""
    definition = FEATURES[key]
    return tuple(
        module
        for module in (definition.parent_module, *definition.requires_modules)
        if module is not None
    )


def prune_features(enabled_features, enabled_modules):
    """Split features into those the module set supports and those it no longer does.

    Removing a module has to remove the features that depend on it. Without this,
    `uninstall_module("payments")` and applying the `minimal` profile both RAISE --
    `payments.enabled` would still be set and would demand the very module being taken
    away, so the operation is impossible rather than merely lossy.

    Keeping the feature instead is not an option: the capability would read as ON while
    every surface behind it was gone. The staff console already works this way (a
    checkbox disabled by its parent module is omitted from the PATCH and clears the
    capability), so this makes the service agree with the UI rather than fight it.

    Returns ``(kept, dropped)``, both sorted in registry order, so the caller can audit
    what it removed rather than dropping it silently.
    """
    modules = set(enabled_modules)
    kept, dropped = [], []
    for definition in FEATURE_DEFINITIONS:
        if definition.key not in set(enabled_features):
            continue
        supported = all(
            module in modules for module in feature_required_modules(definition.key)
        )
        (kept if supported else dropped).append(definition.key)
    return kept, dropped


def validate_capabilities(enabled_modules, enabled_features):
    """Return canonical lists while preserving unknown legacy module keys."""
    modules = _canonical_modules(enabled_modules)
    features = _canonical_features(enabled_features)
    module_set = set(modules)
    errors = {}
    for key, required in module_dependencies().items():
        if key not in module_set:
            continue
        missing = [module for module in required if module not in module_set]
        if missing:
            errors.setdefault("enabled_modules", []).append(
                f"{BY_KEY[key].label} requires "
                f"{', '.join(BY_KEY[module].label.lower() for module in missing)} "
                "to be enabled."
            )
    for key in features:
        definition = FEATURES[key]
        required_modules = [
            module
            for module in (definition.parent_module, *definition.requires_modules)
            if module is not None
        ]
        missing_modules = [
            module
            for module in required_modules
            if module not in module_set or module not in FEATURE_MODULES
        ]
        missing_features = [
            feature for feature in definition.requires_features if feature not in features
        ]
        if missing_modules or missing_features:
            errors.setdefault("enabled_features", []).append(
                f"{key} requires {', '.join(missing_modules + missing_features)} to be enabled."
            )
    if errors:
        raise ValidationError(errors)
    return modules, features


def _canonical_modules(value):
    if not isinstance(value, (list, tuple)) or not all(
        isinstance(key, str) and key for key in value
    ):
        raise ValidationError({"enabled_modules": "Enter a list of non-empty module keys."})
    # Core modules are structural: the system is incoherent without them, so they are
    # added back rather than rejected. Rejecting would make every caller carry the core
    # set, and would fail otherwise-valid operations on a row that somehow lost one.
    # Unknown legacy keys are still preserved -- this only ever adds.
    return sorted(set(value) | core_module_keys())

def _canonical_features(value):
    if not isinstance(value, (list, tuple)) or not all(
        isinstance(key, str) and key for key in value
    ):
        raise ValidationError({"enabled_features": "Enter a list of non-empty feature keys."})
    unknown = sorted(set(value) - FEATURES.keys())
    if unknown:
        raise ValidationError({"enabled_features": f"Unknown feature keys: {', '.join(unknown)}."})
    if len(set(value)) != len(value):
        raise ValidationError({"enabled_features": "Feature keys must not contain duplicates."})
    return [definition.key for definition in FEATURE_DEFINITIONS if definition.key in value]
