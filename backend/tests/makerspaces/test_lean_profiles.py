"""The lean install profiles, and the tombstone suggestion that pairs with them.

Module install and app tombstoning are different axes: a profile decides what a tenant
sees, `TOMBSTONED_APPS` decides what the deployment ships. A self-hoster needs both to run
something small, so these assert the profiles are coherent and that the suggestion command
never proposes removing an app somebody is still using.
"""

import pytest
from django.core.management import call_command
from io import StringIO

from apps.makerspaces.models import Makerspace
from apps.makerspaces.module_profiles import (
    EVERYTHING,
    LENDING,
    MINIMAL,
    PROFILES,
    WORKSHOP,
    profile_modules,
)
from apps.makerspaces.module_registry import BY_KEY, core_module_keys

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("profile", sorted(PROFILES))
def test_every_profile_is_dependency_closed_and_includes_core(profile):
    keys = set(profile_modules(profile))
    assert core_module_keys() <= keys
    for key in keys:
        assert set(BY_KEY[key].requires_modules) <= keys, key


def test_the_lending_profile_ships_no_machine_modules():
    keys = set(profile_modules(LENDING))
    assert "machines" not in keys
    assert "machine_service" not in keys
    assert "printing" not in keys
    # ...but keeps the hardware lifecycle it exists for.
    assert {"stocktake", "containers", "asset_units"} <= keys


def test_the_workshop_profile_ships_machines_but_not_the_lending_extras():
    keys = set(profile_modules(WORKSHOP))
    assert {"machines", "machine_service", "maintenance"} <= keys
    assert "stock_transfers" not in keys
    assert "procurement" not in keys


def test_the_loan_spine_survives_every_profile_including_workshop():
    """Core is core: the Hard Rules require a QR scan and an issue photo to hand over
    hardware, so no profile can drop the request/evidence/scanner spine."""
    for profile in PROFILES:
        keys = set(profile_modules(profile))
        assert {"request_workflow", "evidence_uploads", "qr_management", "scanner"} <= keys


def test_minimal_is_a_subset_of_every_other_profile():
    minimal = set(profile_modules(MINIMAL))
    for profile in PROFILES:
        assert minimal <= set(profile_modules(profile)), profile


def test_everything_is_a_superset_of_every_other_profile():
    everything = set(profile_modules(EVERYTHING))
    for profile in PROFILES:
        assert set(profile_modules(profile)) <= everything, profile


def test_suggest_tombstones_names_apps_no_makerspace_uses():
    Makerspace.objects.create(
        name="lending-only",
        slug="lending-only",
        enabled_modules=profile_modules(LENDING),
    )
    out = StringIO()
    call_command("suggest_tombstones", stdout=out)
    printed = out.getvalue()

    # The lending profile installs no events/bookings/maintenance modules at all.
    assert "events" in printed
    assert "bookings" in printed
    assert "TOMBSTONED_APPS=" in printed


def test_suggest_tombstones_never_proposes_an_app_a_tenant_still_uses():
    # One tenant still using a module must keep the app off the list -- a tombstone is
    # process-global, so removing it would break them.
    Makerspace.objects.create(
        name="lean-space", slug="lean-space", enabled_modules=profile_modules(LENDING)
    )
    Makerspace.objects.create(
        name="full-space", slug="full-space", enabled_modules=profile_modules(EVERYTHING)
    )
    out = StringIO()
    call_command("suggest_tombstones", stdout=out)

    assert "Every separable app with a module key is in use." in out.getvalue()
