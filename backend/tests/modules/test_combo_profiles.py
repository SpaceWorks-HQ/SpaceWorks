"""Install profiles x the registry: the numbers MODULES.md and INVARIANTS.md publish (matrix P1-P4).

Both documents quoted counts that had drifted silently (32 modules, 8 or 10 default
modules, events/bookings profiles of 12). These pins give the published numbers a test to
drift against: change a profile or a default and this fails until the docs are updated too.
"""

import pytest

from apps.makerspaces.module_profiles import PROFILES, profile_modules
from apps.makerspaces.module_registry import (
    MODULE_KEYS,
    core_module_keys,
    default_enabled_module_keys,
    module_dependencies,
)

PUBLISHED_PROFILE_SIZES = {
    "minimal": 6, "workshop": 14, "lending": 17, "recommended": 20, "cloud": 24,
    "everything": 33, "full": 33, "events": 13, "bookings": 13,
}


def test_the_published_module_and_default_counts():
    assert len(MODULE_KEYS) == 33
    assert len(core_module_keys()) == 6
    assert set(default_enabled_module_keys()) == core_module_keys() | {"updates"}


@pytest.mark.parametrize("profile", sorted(PROFILES))
def test_each_profile_has_its_published_size_and_is_dependency_closed(profile):
    modules = set(profile_modules(profile))

    assert len(modules) == PUBLISHED_PROFILE_SIZES[profile]
    assert core_module_keys() <= modules
    for key, required in module_dependencies().items():
        if key in modules:
            assert set(required) <= modules, (profile, key, required)


def test_the_published_module_dependencies():
    assert module_dependencies() == {
        "printing": ("machine_service",),
        "events": ("membership",),
        "bookings": ("membership",),
        "mobile": ("member_accounts",),
    }
