"""Canonical registry of makerspace modules.

Single source of truth for module keys, their defaults, frontend exposure and
inter-module dependencies. The parallel hand-kept lists that used to drift apart
-- ``models.DEFAULT_ENABLED_MODULES``, ``platform.MODULE_WORKFLOWS``,
``capabilities.FEATURE_MODULES`` and the hardcoded ``printing -> machine_service``
rule -- all derive from here now.

This module must NOT import ``apps.makerspaces.models``. ``models`` imports the
derived helpers from here, so the reverse edge would be a circular import.
"""

from apps.makerspaces.module_registry_definitions import (
    FEATURE_PARENT,
    GROUP_BACKUP,
    GROUP_BOOKINGS,
    GROUP_DEVICES,
    GROUP_EVENTS,
    GROUP_INVENTORY,
    GROUP_KEYS,
    GROUP_MACHINES,
    GROUP_MEMBERSHIP,
    GROUP_MOBILE,
    GROUP_NOTIFICATIONS,
    GROUP_PAYMENTS,
    GROUP_REPORTS,
    GROUP_STOCKTAKE,
    GROUP_UPDATES,
    GROUPS,
    GROUPS_BY_KEY,
    GUARD,
    NONE,
    GroupDefinition,
    ModuleDefinition,
)


from apps.makerspaces.module_registry_catalog import MODULES
from apps.makerspaces.module_registry_validation import (
    ImproperlyConfiguredRegistry,
    validate_registry,
)

BY_KEY = {definition.key: definition for definition in MODULES}
MODULE_KEYS = frozenset(BY_KEY)


from apps.makerspaces import module_registry_helpers as _registry_helpers  # noqa: E402

_registry_helpers.BY_KEY = BY_KEY
_registry_helpers.GROUPS = GROUPS
_registry_helpers.GROUPS_BY_KEY = GROUPS_BY_KEY
_registry_helpers.MODULES = MODULES

from apps.makerspaces.module_registry_helpers import (  # noqa: E402
    core_module_keys,
    default_enabled_module_keys,
    dependents_of,
    group_for,
    group_is_always_on,
    group_module_keys,
    is_frontend_exposed,
    module_available,
    module_dependencies,
    module_workflows,
    modules_by_group,
    with_dependencies,
)



def _validate_registry():
    validate_registry(
        MODULES=MODULES, BY_KEY=BY_KEY, GROUPS=GROUPS, GROUPS_BY_KEY=GROUPS_BY_KEY,
        GROUP_KEYS=GROUP_KEYS, group_module_keys=group_module_keys,
    )


_validate_registry()
