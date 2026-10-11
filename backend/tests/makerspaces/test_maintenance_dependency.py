"""Installation must supply the machines required by every maintenance surface."""

import pytest

from apps.makerspaces.models import Makerspace
from apps.makerspaces.module_install import ModuleInstallError, install_module, uninstall_module
from apps.makerspaces.module_registry import core_module_keys


@pytest.mark.django_db
def test_maintenance_install_adds_machines_and_blocks_removing_them_first():
    space = Makerspace.objects.create(
        name="Maintenance only", slug="maintenance-dependency",
        enabled_modules=sorted(core_module_keys()), enabled_features=[],
    )
    assert set(install_module(space, "maintenance")) == {"maintenance", "machines"}
    assert {"maintenance", "machines"} <= set(space.enabled_modules)
    with pytest.raises(ModuleInstallError, match="required by maintenance"):
        uninstall_module(space, "machines")
    assert uninstall_module(space, "maintenance") == ["maintenance"]
    assert uninstall_module(space, "machines") == ["machines"]
