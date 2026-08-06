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
    assert default_enabled_features() == ["inventory.self_checkout"]
    assert not any(key.startswith("payments.") for key in default_enabled_features())


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
    modules, features = validate_capabilities(["machines", "machine_service"], ["payments.machines"])
    assert features == ["payments.machines"]
    assert modules == sorted(core_module_keys() | {"machine_service", "machines"})


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


def test_feature_dependency_and_bootstrap_projection():
    from apps.makerspaces.models import Makerspace
    from apps.makerspaces.platform import bootstrap_payload, feature_enabled

    makerspace = Makerspace(
        id=7,
        name="Machines",
        slug="machines",
        public_code="ABCD",
        public_api_key="pk_test",
        enabled_modules=["machines", "machine_service"],
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


def test_membership_payment_uses_the_registered_membership_module():
    from apps.makerspaces.models import Makerspace
    from apps.makerspaces.platform import feature_enabled

    makerspace = Makerspace(
        name="No membership", slug="no-membership", enabled_modules=["membership"],
        enabled_features=["payments.membership"],
    )
    assert feature_enabled(makerspace, "payments.membership") is True
    modules, features = validate_capabilities(["membership"], ["payments.membership"])
    assert features == ["payments.membership"]
    assert modules == sorted(core_module_keys() | {"membership"})
