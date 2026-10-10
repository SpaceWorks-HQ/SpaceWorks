"""Declared handling for deployment-global uniqueness during materialization."""
from .unique_values_7c import LABEL_UNIQUE_RULES
from .unique_values_7b import PRINTER_UNIQUE_RULES
from .unique_values_core import CORE_UNIQUE_RULES
from .unique_values_devices import DEVICE_UNIQUE_RULES
from .unique_values_policy import (  # noqa: F401 -- re-exported
    FRESH,
    NULL,
    PRESERVE,
    REMAP,
    UniqueValueDisposition,
    UniqueValuePolicy,
    ValueGenerator,
    _policy,
)

# One mapping over every rule set; a per-app extension module adds its own dict here.
DEPLOYMENT_GLOBAL_UNIQUE_RULES = {**CORE_UNIQUE_RULES, **DEVICE_UNIQUE_RULES, **PRINTER_UNIQUE_RULES, **LABEL_UNIQUE_RULES}


def collision_policy(model_label, field_name):
    policy = DEPLOYMENT_GLOBAL_UNIQUE_RULES.get((model_label, f"field:{field_name}"))
    if policy and policy.disposition is PRESERVE:
        return policy
    return None
