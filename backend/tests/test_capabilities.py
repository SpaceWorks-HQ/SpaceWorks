import pytest
from django.core.exceptions import ValidationError

from apps.makerspaces.capabilities import default_enabled_features, validate_capabilities
from apps.makerspaces.module_registry import core_module_keys


def test_feature_registry_rejects_unknown_duplicate_and_missing_dependencies():
    with pytest.raises(ValidationError):
        validate_capabilities(["public_inventory"], ["inventory.unknown"])
    with pytest.raises(ValidationError):
        validate_capabilities(
            ["public_inventory"],
            ["inventory.self_checkout", "inventory.self_checkout"],
        )
    with pytest.raises(ValidationError):
        validate_capabilities(["machines"], ["payments.machines"])


def test_feature_defaults_are_dormant_except_legacy_compatible_self_checkout():
    # The A6 master switches default ON so that adding them changes nothing for a space
    # already using the capability -- they are additive `AND`s in front of readiness
    # checks that stay dormant on their own. `payments.enabled` being on therefore
    # enables nothing by itself: every per-DOMAIN payments feature must still be off by
    # default, which is what the second assertion pins.
    assert default_enabled_features() == [
        "inventory.self_checkout",
        "payments.enabled",
        "mobile.push",
        "presence.geofence",
    ]
    assert not any(
        key.startswith("payments.") and key != "payments.enabled"
        for key in default_enabled_features()
    )


def test_delegated_notification_recipients_default_off_and_match_the_frontend():
    from apps.makerspaces.capabilities import FEATURES

    definition = FEATURES["notifications.delegated_recipients"]
    assert definition.parent_module == "notifications"
    assert definition.default_enabled is False
    assert definition.key not in default_enabled_features()


def test_self_checkout_is_standalone_and_independent_of_public_inventory():
    # Regression: self-checkout / direct handouts previously gated on the standalone
    # `self_checkout` module and NEVER required a public catalogue. A private makerspace
    # that enables the feature must keep it effective.
    #
    # `public_inventory` is now a core module, so "private" is expressed by the
    # `public_inventory_enabled` catalogue switch rather than by omitting the module.
    from apps.makerspaces.models import Makerspace
    from apps.makerspaces.platform import feature_enabled

    private = Makerspace(
        name="Private", slug="private",
        enabled_modules=["staff_admin", "scanner"],
        enabled_features=["inventory.self_checkout"],
        public_inventory_enabled=False,
    )
    assert feature_enabled(private, "inventory.self_checkout") is True
    # And it validates with no parent module requested: canonicalization adds only the
    # core modules, never a parent for this standalone feature.
    modules, features = validate_capabilities([], ["inventory.self_checkout"])
    assert features == ["inventory.self_checkout"]
    assert modules == sorted(core_module_keys())


def test_machine_payment_requires_machines_and_machine_service():
    # `payments` joined the requirement in phase 3, so charging for machine jobs now
    # needs both the domain that produces the charge and the module that takes money.
    modules, features = validate_capabilities(
        ["machines", "machine_service", "payments"], ["payments.machines"]
    )
    assert features == ["payments.machines"]
    assert modules == sorted(core_module_keys() | {"machine_service", "machines", "payments"})


def test_a_payment_feature_without_the_payments_module_is_refused():
    with pytest.raises(ValidationError, match="payments.machines requires payments"):
        validate_capabilities(["machines", "machine_service"], ["payments.machines"])


def test_effective_feature_requires_parent_and_typed_guard():
    from rest_framework.exceptions import ValidationError as DrfValidationError

    from apps.makerspaces.guards import require_feature
    from apps.makerspaces.models import Makerspace
    from apps.makerspaces.platform import feature_enabled

    makerspace = Makerspace(
        name="Dormant", slug="dormant", enabled_modules=["public_inventory"], enabled_features=[]
    )
    assert feature_enabled(makerspace, "inventory.self_checkout") is False
    with pytest.raises(DrfValidationError) as exc:
        require_feature(makerspace, "inventory.self_checkout")
    assert "feature" in exc.value.detail


def test_model_and_admin_validator_share_printing_rule():
    from apps.makerspaces.models import Makerspace

    makerspace = Makerspace(
        name="Print", slug="print", enabled_modules=["printing"], enabled_features=[]
    )
    with pytest.raises(ValidationError) as exc:
        makerspace.clean()
    assert "enabled_modules" in exc.value.message_dict
    with pytest.raises(ValidationError):
        validate_capabilities(["printing"], [])


@pytest.mark.django_db
def test_feature_dependency_and_bootstrap_projection():
    from apps.makerspaces.models import Makerspace
    from apps.makerspaces.platform import bootstrap_payload, feature_enabled

    makerspace = Makerspace(
        id=7,
        name="Machines",
        slug="machines",
        public_code="ABCD",
        public_api_key="pk_test",
        enabled_modules=["machines", "machine_service", "payments"],
        enabled_features=["payments.machines"],
    )
    assert feature_enabled(makerspace, "payments.machines") is True
    payload = bootstrap_payload(makerspace)
    assert payload["features"] == ["payments.machines"]
    assert "telegram_bot_token" not in payload

def test_staff_serializer_splits_module_and_feature_capability_writes():
    from rest_framework.exceptions import PermissionDenied
    from rest_framework.exceptions import ValidationError as DrfValidationError
    from rest_framework.test import APIRequestFactory

    from apps.admin_api.serializers_makerspaces import MakerspaceSerializer
    from apps.makerspaces.models import Makerspace

    request = APIRequestFactory().patch("/makerspaces/1", {})
    module_serializer = MakerspaceSerializer(
        Makerspace(name="Modules", slug="modules"),
        data={"enabled_modules": ["public_inventory"]},
        partial=True,
        context={"request": request},
    )
    with pytest.raises(PermissionDenied):
        module_serializer.is_valid(raise_exception=True)

    enabled_feature_serializer = MakerspaceSerializer(
        Makerspace(
            name="Feature enabled",
            slug="feature-enabled",
            enabled_modules=["public_inventory"],
            enabled_features=[],
        ),
        data={"enabled_features": ["inventory.self_checkout"]},
        partial=True,
        context={"request": request},
    )
    assert enabled_feature_serializer.is_valid(raise_exception=True) is True
    assert enabled_feature_serializer.validated_data["enabled_features"] == [
        "inventory.self_checkout"
    ]

    disabled_feature_serializer = MakerspaceSerializer(
        Makerspace(
            name="Feature disabled",
            slug="feature-disabled",
            enabled_modules=["public_inventory"],
            enabled_features=[],
        ),
        data={"enabled_features": ["payments.machines"]},
        partial=True,
        context={"request": request},
    )
    with pytest.raises(DrfValidationError):
        disabled_feature_serializer.is_valid(raise_exception=True)


def test_admin_form_rejects_child_without_parent_even_when_ui_is_bypassed():
    from apps.makerspaces.admin_capabilities import MakerspaceAdminForm
    from apps.makerspaces.models import Makerspace

    form = MakerspaceAdminForm(instance=Makerspace(name="Admin", slug="admin"))
    form.cleaned_data = {"capabilities": ["feature:payments.machines"]}
    with pytest.raises(Exception):
        form.clean_capabilities()

def test_admin_form_allows_standalone_self_checkout_without_a_parent_module():
    # The /control/ matrix must persist a parentless feature even when the operator
    # selected no parent module for it (P2 silent-clear guard).
    from apps.makerspaces.admin_capabilities import MakerspaceAdminForm
    from apps.makerspaces.models import Makerspace

    instance = Makerspace(name="Private admin", slug="private-admin")
    form = MakerspaceAdminForm(instance=instance)
    form.cleaned_data = {
        "capabilities": ["module:staff_admin", "feature:inventory.self_checkout"]
    }
    form.clean_capabilities()
    assert "inventory.self_checkout" in instance.enabled_features
    # Only core modules are added back; no optional module is inferred from the feature.
    assert set(instance.enabled_modules) == core_module_keys() | {"staff_admin"}


def test_admin_form_offers_every_registered_module_on_a_fresh_makerspace():
    # The matrix used to build its choices from "defaults + keys already on the row",
    # so a module that was not default-on could never be switched on for a makerspace
    # that did not already have it -- `notifications` was enforced but unreachable.
    # Now that modules are opt-in, that bug would hide almost the whole registry.
    from apps.makerspaces.admin_capabilities import MakerspaceAdminForm
    from apps.makerspaces.models import Makerspace
    from apps.makerspaces.module_registry import MODULES

    form = MakerspaceAdminForm(instance=Makerspace(name="Fresh", slug="fresh"))
    offered = {value for value, _ in form.fields["capabilities"].choices}

    assert "module:notifications" in offered
    assert {f"module:{definition.key}" for definition in MODULES} <= offered


def test_admin_form_keeps_unrecognised_stored_module_keys_selectable():
    # A legacy key not in the registry must stay checkable, or saving an untouched
    # form would silently drop it.
    from apps.makerspaces.admin_capabilities import MakerspaceAdminForm
    from apps.makerspaces.models import Makerspace

    instance = Makerspace(name="Legacy", slug="legacy", enabled_modules=["staff_admin", "old_thing"])
    form = MakerspaceAdminForm(instance=instance)
    offered = {value for value, _ in form.fields["capabilities"].choices}

    assert "module:old_thing" in offered
    assert "module:old_thing" in form.initial["capabilities"]


def test_membership_payment_uses_the_registered_membership_module():
    from apps.makerspaces.models import Makerspace
    from apps.makerspaces.platform import feature_enabled

    # Membership dues require the community and payments modules. Identity may come
    # from external OIDC, so built-in member accounts are independent.
    makerspace = Makerspace(
        name="No membership", slug="no-membership",
        enabled_modules=["membership", "member_accounts", "payments"],
        enabled_features=["payments.membership"],
    )
    assert feature_enabled(makerspace, "payments.membership") is True
    modules, features = validate_capabilities(
        ["membership", "member_accounts", "payments"], ["payments.membership"]
    )
    assert features == ["payments.membership"]
    assert modules == sorted(core_module_keys() | {"membership", "member_accounts", "payments"})


def test_membership_without_builtin_member_accounts_is_valid():
    modules, features = validate_capabilities(["membership"], [])

    assert modules == sorted(core_module_keys() | {"membership"})
    assert features == []


def test_frontend_feature_definitions_match_the_backend():
    """`frontend/src/lib/features.ts` is a hand-kept mirror of the backend registry.

    The staff console renders this hand-kept copy; a missing feature is invisible, while
    a stale parent disables the wrong checkbox and can silently clear the capability.
    """
    import json
    import re
    from pathlib import Path

    from apps.makerspaces.capabilities import FEATURE_DEFINITIONS

    source = (
        Path(__file__).resolve().parents[2] / "frontend" / "src" / "lib" / "features.ts"
    ).read_text(encoding="utf-8")
    body = source.split("FEATURE_DEFINITIONS: readonly FeatureDefinition[] = [", 1)[1]
    body = body.split("];", 1)[0]

    mirrored = []
    for line in body.splitlines():
        match = re.search(
            r'key:\s*"([^"]+)",\s*parent_module:\s*(null|"[^"]*"),\s*label:\s*"([^"]+)"',
            line,
        )
        if match:
            key, parent, label = match.groups()
            mirrored.append((key, None if parent == "null" else json.loads(parent), label))

    expected = [
        (definition.key, definition.parent_module, definition.label)
        for definition in FEATURE_DEFINITIONS
        if definition.frontend_exposed
    ]
    assert sorted(mirrored) == sorted(expected), (
        "frontend/src/lib/features.ts has drifted from capabilities.FEATURE_DEFINITIONS."
    )
