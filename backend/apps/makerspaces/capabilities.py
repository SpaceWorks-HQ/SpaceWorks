"""Canonical feature catalog and validation, explicit compatibility exports."""
from .capability_definitions import FeatureDefinition, FEATURE_DEFINITIONS, FEATURES, FEATURE_MODULES
from .capability_validation import (
    default_enabled_features, feature_required_modules, prune_features,
    validate_capabilities, _canonical_features, _canonical_modules,
)
