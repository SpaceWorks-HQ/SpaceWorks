"""Editions hide surfaces and public routes; they never change what a makerspace can do."""
import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.makerspaces import editions
from apps.makerspaces.module_profiles import EVENTS_ONLY, BOOKINGS_ONLY, EVERYTHING, profile_modules
from apps.makerspaces.module_registry import MODULE_KEYS
from apps.makerspaces.module_registry_helpers import core_module_keys
from apps.makerspaces.platform import available_modules, bootstrap_payload, module_enabled
from tests.return_helpers import authenticated_client, make_member, make_product, make_space

pytestmark = pytest.mark.django_db


def test_every_hidden_key_is_a_real_module_and_core_is_never_uninstalled():
    for edition in editions.EDITIONS.values():
        assert edition.hidden_module_keys <= MODULE_KEYS, edition.key
    assert core_module_keys() <= set(profile_modules(EVENTS_ONLY))
    assert core_module_keys() <= set(profile_modules(BOOKINGS_ONLY))
    assert "events" in profile_modules(EVENTS_ONLY) and "bookings" not in profile_modules(EVENTS_ONLY)
    assert "bookings" in profile_modules(BOOKINGS_ONLY) and "events" not in profile_modules(BOOKINGS_ONLY)
    assert set(profile_modules(EVENTS_ONLY)) <= set(profile_modules(EVERYTHING))


def test_unknown_edition_is_refused(settings):
    settings.SPACEWORKS_EDITION = "kitchen"
    with pytest.raises(Exception):
        editions.current_edition()


def test_events_edition_hides_the_loan_spine_from_clients_but_not_from_capability(settings):
    space = make_space("edition-events")
    settings.SPACEWORKS_EDITION = "makerspace"
    assert "public_inventory" in available_modules(space)
    settings.SPACEWORKS_EDITION = "events"
    listed = available_modules(space)
    assert "public_inventory" not in listed and "scanner" not in listed and "bookings" not in listed
    assert "events" in listed
    # Capability is untouched: workflows, gates and staff endpoints keep working.
    assert module_enabled(space, "public_inventory") is True
    assert core_module_keys() <= set(space.enabled_modules)
    payload = bootstrap_payload(space)
    assert payload["edition"] == "events"
    assert "request_workflow" not in payload["modules"]


def test_events_edition_makes_public_loan_routes_404_but_staff_routes_answer(settings):
    space = make_space("edition-public")
    make_product(space, name="Hidden Drill")
    manager = make_member("edition-manager", space)
    public_url = reverse("public-inventory", kwargs={"makerspace_slug": space.slug})
    staff_url = reverse("admin-inventory", kwargs={"makerspace_id": space.pk})

    settings.SPACEWORKS_EDITION = "makerspace"
    assert APIClient().get(public_url).status_code == 200
    settings.SPACEWORKS_EDITION = "events"
    assert APIClient().get(public_url).status_code == 404
    assert authenticated_client(manager).get(staff_url).status_code == 200
    assert APIClient().get(reverse("public-machines", kwargs={"makerspace_slug": space.slug})).status_code == 404


def test_bookings_edition_hides_events_and_organization_edition_hides_nothing(settings):
    space = make_space("edition-bookings")
    settings.SPACEWORKS_EDITION = "bookings"
    listed = available_modules(space)
    assert "events" not in listed and "bookings" in listed
    settings.SPACEWORKS_EDITION = "organization"
    assert set(available_modules(space)) >= core_module_keys()
    assert editions.current_edition().organization_label is True
    assert bootstrap_payload(space)["edition"] == "organization"
