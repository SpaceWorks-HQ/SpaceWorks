from importlib import import_module

import pytest
from django.apps import apps

from apps.makerspaces.capabilities import FEATURE_MODULES
from apps.makerspaces.models import DEFAULT_ENABLED_MODULES
from apps.makerspaces.module_profiles import EVERYTHING, profile_modules
from tests.return_helpers import make_space


pytestmark = pytest.mark.django_db
migration = import_module(
    "apps.makerspaces.migrations.0049_membership_dues_and_module"
)


def test_membership_module_migration_preserves_existing_entries_and_is_idempotent():
    makerspace = make_space("membership-payment-module")
    makerspace.enabled_modules = ["custom", "bookings"]
    makerspace.save(update_fields=["enabled_modules"])

    migration.enable_membership(apps, None)
    migration.enable_membership(apps, None)
    makerspace.refresh_from_db()

    assert makerspace.enabled_modules == ["custom", "bookings", "membership"]


def test_membership_is_a_default_feature_module():
    makerspace = make_space("membership-payment-default")

    # Opt-in: installable rather than on by default, but still a valid feature parent.
    assert "membership" not in DEFAULT_ENABLED_MODULES
    assert "membership" in profile_modules(EVERYTHING)
    assert "membership" in FEATURE_MODULES
    assert "membership" in makerspace.enabled_modules
