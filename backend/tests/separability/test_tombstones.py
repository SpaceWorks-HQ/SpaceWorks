"""Plan B5 — the deployment-level tombstone switch, and what it is not allowed to do.

Two properties matter here and they pull in opposite directions.

*Runtime surfaces must disappear.* A tombstoned app's URLs, admin screens, sidebar
entries and module key have to stop being offered, or the console renders a tab whose
every request 404s — the failure B5 calls out by name.

*Retention must survive.* The rows, the migrations, the purge plan and the PII
mapping all stay exactly as they were. A tombstone that deregistered those would make
retained data unpurgeable and strand private objects nothing can name, which is the
whole reason the registries were split in two.

Surfaces wired at import time (URLconf, admin registration, the Unfold sidebar) cannot
be re-derived inside a running process, so the assertions here work on the manifest and
the functions that read it. The end-to-end proof is a separate tombstone-profile run —
see `tests/tombstone/`.
"""

import pytest
from django.contrib import admin
from django.test import override_settings

from apps.admin_api.serializers_makerspace_aux import MakerspaceSwitcherSerializer
from apps.makerspaces.models import Makerspace
from apps.makerspaces.module_install import (
    ModuleInstallError,
    apply_profile,
    install_module,
    module_status,
)
from apps.makerspaces.module_profiles import EVERYTHING
from apps.makerspaces.module_registry import MODULES, module_available
from apps.makerspaces.platform import available_modules, bootstrap_payload, module_enabled
from apps.procurement.models import ToBuyItem, ToBuyReceipt
from apps.separability import checks
from apps.separability.registry import registered_purge_modules, runtime_active
from apps.separability.tombstones import SEPARABLE_APPS, tombstoned_app_labels

TARGET = "procurement"


@pytest.fixture
def tombstoned(monkeypatch):
    """Report one app as tombstoned to everything that consults the manifest.

    Patching the accessor rather than the private map is deliberate: it is the same
    indirection production code goes through, so a consumer that reverted to an
    imported snapshot would not be fooled by this fixture either.
    """

    def _tombstone(app_label=TARGET):
        monkeypatch.setattr(
            "apps.separability.registry.runtime_active",
            lambda label: label != app_label,
        )
        return app_label

    return _tombstone


def make_space(slug="tombstone-target", **extra):
    return Makerspace.objects.create(name=slug, slug=slug, **extra)


def with_procurement(space):
    space.enabled_modules = sorted(set(space.enabled_modules) | {TARGET})
    space.save(update_fields=["enabled_modules"])
    return space


def _ids(errors):
    return sorted(error.id for error in errors)


# --------------------------------------------------------------------------
# The live assertion: nothing is tombstoned in this profile.
# --------------------------------------------------------------------------

def test_the_default_deployment_tombstones_nothing():
    """Every separable app ships by default; a tombstone is an explicit opt-in."""
    assert tombstoned_app_labels() == frozenset()
    assert runtime_active(TARGET) is True
    assert ToBuyItem in admin.site._registry
    assert ToBuyReceipt in admin.site._registry


def test_the_two_gutted_apps_stay_tombstoned_unconditionally():
    """printing and roadmap have no code left, so no setting can bring them back."""
    assert runtime_active("printing") is False
    assert runtime_active("roadmap") is False


# --------------------------------------------------------------------------
# Runtime: the module reads as off everywhere.
# --------------------------------------------------------------------------

def test_a_tombstoned_module_is_unavailable_even_though_the_key_is_registered(tombstoned):
    tombstoned()
    assert module_available(TARGET) is False
    assert module_available("reports") is True


def test_an_unknown_legacy_key_stays_available():
    """It has no owning app, and dropping it would silently discard a capability."""
    assert module_available("some_legacy_key_the_registry_never_learned") is True


@pytest.mark.django_db
def test_module_enabled_is_false_for_a_tombstoned_app_the_tenant_still_has_enabled(tombstoned):
    space = with_procurement(make_space())
    assert module_enabled(space, TARGET) is True

    tombstoned()

    # The stored row is untouched: a deployment decision must not rewrite tenant data,
    # or removing the label later would not bring the capability back.
    space.refresh_from_db()
    assert TARGET in space.enabled_modules
    assert module_enabled(space, TARGET) is False
    assert TARGET not in available_modules(space)


@pytest.mark.django_db
def test_the_bootstrap_payload_stops_advertising_a_tombstoned_module(tombstoned):
    space = with_procurement(make_space())
    assert TARGET in bootstrap_payload(space)["modules"]

    tombstoned()

    payload = bootstrap_payload(space)
    assert TARGET not in payload["modules"]
    assert TARGET not in payload["workflows"]


@pytest.mark.django_db
def test_the_staff_console_is_told_only_about_modules_the_deployment_serves(tombstoned):
    """This payload is what `filterTabsByEnabledModules` turns into console tabs."""
    space = with_procurement(make_space())
    assert TARGET in MakerspaceSwitcherSerializer(space).data["enabled_modules"]

    tombstoned()

    assert TARGET not in MakerspaceSwitcherSerializer(space).data["enabled_modules"]


# --------------------------------------------------------------------------
# Install path: a dead capability is refused, not quietly written.
# --------------------------------------------------------------------------

@pytest.mark.django_db
def test_installing_a_tombstoned_module_is_refused(tombstoned):
    space = make_space()
    tombstoned()
    with pytest.raises(ModuleInstallError, match="not shipped by this deployment"):
        install_module(space, TARGET)


@pytest.mark.django_db
def test_a_profile_skips_what_the_deployment_does_not_ship(tombstoned):
    """Refusing here would make the setup wizard unusable on a tombstoned build."""
    space = make_space()
    tombstoned()
    resulting = apply_profile(space, EVERYTHING)
    assert TARGET not in resulting
    assert "reports" in resulting


@pytest.mark.django_db
def test_list_modules_reports_availability_separately_from_installation(tombstoned):
    space = make_space()
    tombstoned()
    rows = {row["key"]: row for row in module_status(space)}
    assert rows[TARGET]["available"] is False
    assert rows["reports"]["available"] is True


# --------------------------------------------------------------------------
# Retention: the half that must NOT disappear.
# --------------------------------------------------------------------------

def test_a_tombstoned_app_keeps_its_purge_plan(tombstoned):
    """Deregistering it is what would strand receipts in the private bucket."""
    tombstoned()
    assert TARGET in registered_purge_modules()


@pytest.mark.django_db
def test_a_tombstoned_app_keeps_its_rows(tombstoned):
    space = make_space()
    item = ToBuyItem.objects.create(makerspace=space, name="Filament", quantity=1)
    tombstoned()
    assert ToBuyItem.objects.filter(pk=item.pk).exists()


# --------------------------------------------------------------------------
# Illegal tombstones are refused at startup, not discovered as scattered 404s.
# --------------------------------------------------------------------------

@override_settings(TOMBSTONED_APPS=frozenset({"apps.procurement"}))
def test_a_dotted_path_instead_of_an_app_label_fails_the_system_check():
    """The most expensive typo: it reads as a working tombstone and does nothing."""
    assert _ids(checks.check_tombstones_are_legal(None)) == ["separability.E007"]


@override_settings(TOMBSTONED_APPS=frozenset({TARGET}))
def test_a_legal_tombstone_passes_the_system_check():
    assert checks.check_tombstones_are_legal(None) == []


def test_no_core_module_s_app_is_declared_separable():
    """Removing a core app's surfaces yields a broken install, not a smaller one."""
    core_apps = {definition.app_label for definition in MODULES if definition.is_core}
    assert SEPARABLE_APPS & core_apps == set()


def test_every_app_outside_the_separable_set_is_refused():
    """Including the tenant root, which owns only non-core modules and is not separable."""
    for app_label in ("makerspaces", "inventory", "accounts", "payments", "encryption"):
        with override_settings(TOMBSTONED_APPS=frozenset({app_label})):
            assert _ids(checks.check_tombstones_are_legal(None)) == ["separability.E007"], app_label


def test_every_separable_app_registers_a_runtime_state():
    """Declared separable but never registering leaves `runtime_active` guessing True."""
    from apps.separability.registry import registered_runtime_apps

    assert SEPARABLE_APPS <= registered_runtime_apps()
