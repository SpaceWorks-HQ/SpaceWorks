"""Canonical makerspace module and feature capability definitions."""

from dataclasses import dataclass

from django.core.exceptions import ValidationError

from apps.makerspaces.module_registry import (
    BY_KEY,
    MODULE_KEYS,
    core_module_keys,
    module_dependencies,
)


@dataclass(frozen=True)
class FeatureDefinition:
    key: str
    # None => standalone feature with no parent-module prerequisite (effective purely
    # when enabled). Used for capabilities that are not a child of any single module,
    # e.g. self-checkout / direct handouts, which a private makerspace runs without a
    # public catalogue. A string parent must be a registered module key.
    parent_module: str | None
    label: str
    description: str = ""
    default_enabled: bool = False
    requires_modules: tuple[str, ...] = ()
    requires_features: tuple[str, ...] = ()
    frontend_exposed: bool = True


FEATURE_DEFINITIONS = (
    FeatureDefinition(
        "payments.machines", "machines", "Machine payments",
        "Charge for machine service requests via Stripe.",
        requires_modules=("machine_service",),
    ),
    FeatureDefinition(
        "payments.bookings", "bookings", "Booking payments",
        "Charge for resource bookings via Stripe.",
    ),
    FeatureDefinition(
        "payments.events", "events", "Event payments",
        "Charge for event registrations via Stripe.",
    ),
    FeatureDefinition(
        "payments.membership", "membership", "Membership payments",
        "Charge membership dues via Stripe.",
    ),
    FeatureDefinition(
        "inventory.self_checkout", None, "Self checkout",
        "Member self-checkout and staff direct handouts of QR tools.",
        default_enabled=True,
    ),
    # The three below are standalone master switches (plan A6). Each is an additive
    # `AND` in front of an existing readiness check, never a replacement -- turning one
    # ON must not make an unconfigured capability start working. They default ENABLED so
    # that adding them changes nothing for a makerspace that was already using the
    # capability; migration 0051 backfills the same keys onto rows that predate them.
    FeatureDefinition(
        "payments.enabled", None, "Payments",
        "Master switch for online payments; each domain still needs its own "
        "payments.* feature and configured Stripe credentials.",
        default_enabled=True,
    ),
    FeatureDefinition(
        "mobile.push", None, "Native push",
        "Native push notifications to this makerspace's registered devices; still "
        "requires platform FCM/APNs credentials.",
        default_enabled=True,
    ),
    FeatureDefinition(
        "presence.geofence", None, "Presence geofence",
        "Advisory proximity classification on check-in; still requires the makerspace "
        "geofence to be configured. Never an access gate.",
        default_enabled=True,
    ),
)
FEATURES = {definition.key: definition for definition in FEATURE_DEFINITIONS}
# A feature's parent/required modules are validated against the module registry
# rather than a hand-kept set, so adding a module can no longer leave a valid
# parent silently unrecognised (which would disable the feature).
FEATURE_MODULES = MODULE_KEYS


def default_enabled_features():
    """Return the enabled-by-default features for a new makerspace."""
    return [definition.key for definition in FEATURE_DEFINITIONS if definition.default_enabled]


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
