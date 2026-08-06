from importlib import import_module

from django.apps import apps
import pytest

from apps.makerspaces.models import DEFAULT_ENABLED_MODULES
from apps.makerspaces.module_profiles import EVERYTHING, profile_modules
from apps.makerspaces.platform import MODULE_WORKFLOWS
from tests.return_helpers import make_space


pytestmark = pytest.mark.django_db
migration = import_module(
    "apps.makerspaces.migrations.0034_enable_maintenance_module"
)


def test_module_migration_is_idempotent_and_preserves_custom_flags():
    makerspace = make_space("maintenance-module-migration")
    makerspace.enabled_modules = ["custom", "machines"]
    makerspace.save(update_fields=["enabled_modules"])

    migration.enable_maintenance(apps, None)
    migration.enable_maintenance(apps, None)
    makerspace.refresh_from_db()

    assert makerspace.enabled_modules == ["custom", "machines", "maintenance"]
    migration.disable_maintenance(apps, None)
    makerspace.refresh_from_db()
    assert makerspace.enabled_modules == ["custom", "machines"]


def test_new_makerspaces_and_platform_workflow_include_maintenance():
    makerspace = make_space("maintenance-module-default")
    # Modules are opt-in now, so `maintenance` ships as an installable module rather
    # than an on-by-default one.
    assert "maintenance" not in DEFAULT_ENABLED_MODULES
    assert "maintenance" in profile_modules(EVERYTHING)
    assert "maintenance" in makerspace.enabled_modules
    assert MODULE_WORKFLOWS["maintenance"] == ["maintenance"]
