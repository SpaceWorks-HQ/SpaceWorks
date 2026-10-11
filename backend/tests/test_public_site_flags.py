import pytest
from django.test import RequestFactory
from django.urls import reverse

from apps.inventory.middleware import FrontendHMACMiddleware
from apps.makerspaces.migrations import __name__ as migrations_package
from tests.modules.family_helpers import client, family_space

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("site,catalogue", [(True, True), (True, False), (False, True), (False, False)])
def test_directory_and_embed_key_follow_site_while_catalogue_has_its_own_gate(site, catalogue):
    space = family_space(f"public-flags-{site}-{catalogue}", "machines", loans=True)
    space.public_site_enabled, space.public_inventory_enabled = site, catalogue
    space.cors_allowed_origins = ["https://embed.example.test"]
    space.save(update_fields=["public_site_enabled", "public_inventory_enabled", "cors_allowed_origins"])
    directory = client().get(reverse("public-makerspaces"))
    assert directory.status_code == 200
    assert (space.slug in {row["slug"] for row in directory.data}) is site
    catalogue_response = client().get(reverse("public-inventory", args=[space.slug]))
    assert catalogue_response.status_code == (200 if site and catalogue else 404)
    machines = client().get(reverse("public-machines", args=[space.slug]))
    assert machines.status_code == (200 if site else 404)
    request = RequestFactory().get(reverse("public-machines", args=[space.slug]),
        HTTP_X_PUBLISHABLE_KEY=space.public_api_key, HTTP_ORIGIN="https://embed.example.test")
    middleware = FrontendHMACMiddleware(lambda request: None)
    assert middleware._publishable_key_is_valid(request) is site


def test_site_embed_key_cannot_read_another_tenant_machine_list():
    own, other = family_space("embed-own", "machines"), family_space("embed-other", "machines")
    own.cors_allowed_origins = ["https://embed.example.test"]
    own.save(update_fields=["cors_allowed_origins"])
    request = RequestFactory().get(reverse("public-machines", args=[other.slug]),
        HTTP_X_PUBLISHABLE_KEY=own.public_api_key, HTTP_ORIGIN="https://embed.example.test")
    assert FrontendHMACMiddleware(lambda request: None)._publishable_key_is_valid(request) is False


def test_machines_module_off_is_a_bad_request():
    space = family_space("public-machines-module-off", loans=True)
    result = client().get(reverse("public-machines", args=[space.slug]))
    assert result.status_code == 400 and "machines" in str(result.data)


def test_migration_preserves_old_publication_and_enables_loans():
    import importlib
    from django.db import connection
    from django.apps import apps
    from types import SimpleNamespace

    space = family_space("public-site-backfill", loans=False)
    space.public_inventory_enabled = False
    space.save(update_fields=["public_inventory_enabled"])
    migration = importlib.import_module(f"{migrations_package}.0086_public_site_and_loans")
    migration.preserve_publication_and_loans(apps, SimpleNamespace(connection=connection))
    space.refresh_from_db()
    assert space.public_site_enabled is False
    assert "loans.enabled" in space.enabled_features
