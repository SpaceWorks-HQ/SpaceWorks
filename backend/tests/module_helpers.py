"""Helpers for turning modules off in tests.

`uninstall_module` deliberately REFUSES to remove a module that another enabled module
declares a dependency on: disabling `membership` underneath an enabled `events` would
leave every registration surface mounted and refusing, which is the failure mode the
dependency was declared to prevent. A test that wants a membership-off makerspace
therefore has to remove the dependents too. This does that transitively so each test can
state its intent ("no membership") instead of hand-maintaining a dependency closure that
changes whenever the registry does.
"""

from apps.makerspaces.module_install import uninstall_module
from apps.makerspaces.module_registry_helpers import dependents_of


def disable_module(makerspace, key, actor=None):
    """Uninstall `key`, uninstalling whatever depends on it first, deepest dependent first."""
    makerspace.refresh_from_db()
    enabled = set(makerspace.enabled_modules or [])
    if key not in enabled:
        return []
    for dependent in dependents_of(key, enabled - {key}):
        disable_module(makerspace, dependent, actor=actor)
    return uninstall_module(makerspace, key, actor=actor)
