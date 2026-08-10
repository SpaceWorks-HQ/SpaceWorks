"""Install path for opt-in modules (plan 3.1/3.2).

Opt-in modules are only safe to ship alongside a way to install them, because
/control/ is deliberately not proxied on the public frontend port -- a
non-technical operator cannot reach it.
"""

from io import StringIO

import pytest
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.management import CommandError, call_command

from apps.audit.models import AuditLog
from apps.makerspaces.capabilities import validate_capabilities
from apps.makerspaces.models import Makerspace
from apps.makerspaces.module_install import (
    ModuleInstallError,
    apply_profile,
    install_module,
    module_status,
    uninstall_module,
)
from apps.makerspaces.module_profiles import (
    EVERYTHING,
    MINIMAL,
    PROFILES,
    RECOMMENDED,
    profile_modules,
)
from apps.makerspaces.module_registry import MODULE_KEYS, core_module_keys

pytestmark = pytest.mark.django_db


def make_space(slug="install-target"):
    return Makerspace.objects.create(name=slug, slug=slug)


def test_profiles_are_dependency_closed_and_ordered_by_size():
    minimal, recommended, everything = (
        set(profile_modules(name)) for name in (MINIMAL, RECOMMENDED, EVERYTHING)
    )
    assert minimal == core_module_keys()
    assert minimal < recommended < everything
    assert everything == set(MODULE_KEYS)
    for name in PROFILES:
        keys = set(profile_modules(name))
        for key in keys:
            # A profile that enables `printing` without `machine_service` would be
            # rejected by validate_capabilities the moment it was applied.
            assert set(_requires(key)) <= keys


def _requires(key):
    from apps.makerspaces.module_registry import BY_KEY

    return BY_KEY[key].requires_modules


def test_unknown_profile_is_rejected():
    with pytest.raises(ValueError):
        profile_modules("enormous")


def test_apply_profile_sets_modules_and_keeps_unknown_legacy_keys():
    space = make_space()
    space.enabled_modules = ["legacy_thing"]
    space.save(update_fields=["enabled_modules"])

    apply_profile(space, RECOMMENDED)

    space.refresh_from_db()
    assert set(space.enabled_modules) == set(profile_modules(RECOMMENDED)) | {"legacy_thing"}


def test_minimal_profile_leaves_the_public_catalogue_switched_off():
    # `public_inventory` is core so the module cannot express "private makerspace";
    # the catalogue switch does. A minimal install must not publish by default.
    space = make_space("minimal-space")
    assert space.public_inventory_enabled is True

    apply_profile(space, MINIMAL)

    space.refresh_from_db()
    assert space.public_inventory_enabled is False
    assert set(space.enabled_modules) == core_module_keys()


def test_recommended_profile_leaves_the_catalogue_on():
    space = make_space("recommended-space")
    apply_profile(space, RECOMMENDED)
    space.refresh_from_db()
    assert space.public_inventory_enabled is True


def test_install_pulls_in_required_modules_and_audits():
    space = make_space()
    apply_profile(space, MINIMAL)
    # AuditLog is append-only (Postgres trigger), so count the delta rather than
    # clearing the table.
    before = AuditLog.objects.filter(action="makerspace.capabilities_changed").count()

    added = install_module(space, "printing")

    space.refresh_from_db()
    assert set(added) == {"printing", "machine_service"}
    assert {"printing", "machine_service"} <= set(space.enabled_modules)
    after = AuditLog.objects.filter(action="makerspace.capabilities_changed").count()
    assert after == before + 1


def test_installing_twice_is_a_no_op():
    space = make_space()
    apply_profile(space, EVERYTHING)
    assert install_module(space, "reports") == []


def test_unknown_module_cannot_be_installed_or_uninstalled():
    space = make_space()
    with pytest.raises(ModuleInstallError):
        install_module(space, "teleporter")
    with pytest.raises(ModuleInstallError):
        uninstall_module(space, "teleporter")


@pytest.mark.parametrize("key", sorted(core_module_keys()))
def test_core_modules_cannot_be_uninstalled(key):
    space = make_space()
    apply_profile(space, EVERYTHING)
    with pytest.raises(ModuleInstallError, match="core module"):
        uninstall_module(space, key)
    space.refresh_from_db()
    assert key in space.enabled_modules


def test_core_modules_survive_an_attempt_to_save_without_them():
    # Canonicalization adds core back rather than rejecting, so no valid operation
    # fails on a row that somehow lost one.
    space = make_space()
    space.enabled_modules = ["reports"]
    space.enabled_features = []
    space.clean()
    assert core_module_keys() <= set(space.enabled_modules)


def test_clean_prunes_an_orphaned_feature_rather_than_refusing():
    """`clean()` NORMALIZES; the explicit call sites are what validate.

    This reverses the rule phase 3 shipped, and the reason is in the phase 11 report:
    refusing here made a row unsaveable rather than merely lossy. A makerspace created
    with a narrow `enabled_modules` still takes the FIELD default for
    `enabled_features` — which includes the default-on `payments.enabled` and
    `mobile.push` — so it was born inconsistent and then rejected every later save,
    including ones touching neither field.

    The operator-facing strictness did not move: `/control/`'s capability matrix and
    `module_install` call `validate_capabilities` directly, so a conflict somebody
    actually expressed is still reported instead of silently cleared.
    """
    space = make_space()
    space.enabled_modules = ["reports"]
    space.enabled_features = ["payments.enabled"]

    space.clean()

    assert "payments.enabled" not in space.enabled_features


def test_the_control_matrix_still_reports_an_orphaned_feature():
    # The strict path, unchanged: this is what the /control/ capability matrix calls
    # before saving, and it must name the conflict rather than quietly dropping it.
    with pytest.raises(DjangoValidationError, match="payments.enabled requires payments"):
        validate_capabilities(["reports"], ["payments.enabled"])


def test_a_narrowly_created_makerspace_can_still_be_saved():
    # The regression this rule exists for, end to end.
    space = Makerspace.objects.create(
        name="narrow", slug="narrow-modules", enabled_modules=["reports"]
    )
    space.public_stats_enabled = True
    space.full_clean()
    space.save()
    space.refresh_from_db()
    assert space.public_stats_enabled is True


def test_uninstalling_a_module_drops_the_features_that_needed_it():
    space = make_space()
    apply_profile(space, EVERYTHING)
    space.enabled_features = ["payments.enabled", "payments.bookings", "inventory.self_checkout"]
    space.save(update_fields=["enabled_features"])

    uninstall_module(space, "payments")
    space.refresh_from_db()

    # Without this the uninstall would be impossible, not merely lossy: the feature
    # would still demand the module being removed.
    assert "payments.enabled" not in space.enabled_features
    assert "payments.bookings" not in space.enabled_features
    # An unrelated feature is untouched.
    assert "inventory.self_checkout" in space.enabled_features


def test_uninstall_is_refused_while_a_dependent_module_is_installed():
    space = make_space()
    apply_profile(space, EVERYTHING)

    with pytest.raises(ModuleInstallError, match="required by printing"):
        uninstall_module(space, "machine_service")

    uninstall_module(space, "printing")
    assert uninstall_module(space, "machine_service") == ["machine_service"]


def test_uninstall_keeps_data_and_reinstall_restores_the_capability():
    space = make_space()
    apply_profile(space, EVERYTHING)

    uninstall_module(space, "reports")
    space.refresh_from_db()
    assert "reports" not in space.enabled_modules

    install_module(space, "reports")
    space.refresh_from_db()
    assert "reports" in space.enabled_modules


def test_uninstalling_a_module_that_is_not_installed_is_a_no_op():
    space = make_space()
    apply_profile(space, MINIMAL)
    assert uninstall_module(space, "reports") == []


def test_module_status_reports_core_as_installed_regardless_of_stored_state():
    space = make_space()
    space.enabled_modules = []
    space.save(update_fields=["enabled_modules"])

    rows = {row["key"]: row for row in module_status(space)}
    assert len(rows) == len(MODULE_KEYS)
    for key in core_module_keys():
        assert rows[key]["core"] is True
        assert rows[key]["installed"] is True
    assert rows["reports"]["installed"] is False
    assert rows["printing"]["requires"] == ["machine_service"]


def test_list_modules_command_shows_every_module():
    space = make_space("cli-space")
    apply_profile(space, MINIMAL)
    out = StringIO()

    call_command("list_modules", makerspace=space.slug, stdout=out)

    output = out.getvalue()
    for key in MODULE_KEYS:
        assert key in output
    assert "core" in output


def test_install_and_uninstall_commands_round_trip():
    space = make_space("cli-round-trip")
    apply_profile(space, MINIMAL)
    out = StringIO()

    call_command("install_module", "printing", makerspace=space.slug, stdout=out)
    space.refresh_from_db()
    assert {"printing", "machine_service"} <= set(space.enabled_modules)
    # The operator asked for one module; the pulled-in dependency must be named.
    assert "machine_service" in out.getvalue()

    call_command("uninstall_module", "printing", makerspace=space.slug, stdout=StringIO())
    space.refresh_from_db()
    assert "printing" not in space.enabled_modules


def test_commands_reject_an_unknown_makerspace_and_an_ambiguous_default():
    make_space("first-space")
    with pytest.raises(CommandError, match="No makerspace with slug"):
        call_command("list_modules", makerspace="nope", stdout=StringIO())

    make_space("second-space")
    with pytest.raises(CommandError, match="More than one makerspace"):
        call_command("list_modules", stdout=StringIO())


def test_uninstall_command_surfaces_a_refusal_as_a_command_error():
    space = make_space("cli-core")
    apply_profile(space, EVERYTHING)
    with pytest.raises(CommandError, match="core module"):
        call_command("uninstall_module", "scanner", makerspace=space.slug, stdout=StringIO())


def test_setup_instance_applies_the_requested_profile_once():
    call_command(
        "setup_instance", "--makerspace-name", "Profiled", "--makerspace-slug", "profiled",
        "--profile", MINIMAL, "--username", "owner", "--password", "not-a-default",
        stdout=StringIO(),
    )
    space = Makerspace.objects.get(slug="profiled")
    assert set(space.enabled_modules) == core_module_keys()

    # Re-running must not rewrite modules the operator has since changed.
    install_module(space, "reports")
    call_command(
        "setup_instance", "--makerspace-name", "Profiled", "--makerspace-slug", "profiled",
        "--profile", MINIMAL, "--username", "owner", "--password", "not-a-default",
        stdout=StringIO(),
    )
    space.refresh_from_db()
    assert "reports" in space.enabled_modules
