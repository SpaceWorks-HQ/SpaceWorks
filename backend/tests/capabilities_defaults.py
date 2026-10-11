import pytest
from django.core.exceptions import ValidationError

from apps.makerspaces.capabilities import default_enabled_features, validate_capabilities
from apps.makerspaces.module_registry import core_module_keys


def test_kiosk_feature_is_standalone_default_off_and_advertises_two_workflows():
    from apps.makerspaces.capabilities import FEATURE_DEFINITIONS, FEATURES
    from apps.makerspaces.platform import FEATURE_WORKFLOWS

    definition = FEATURES["inventory.kiosk"]
    assert definition.parent_module is None
    assert definition.default_enabled is False
    assert "inventory.kiosk" not in default_enabled_features()
    # Merged lanes added billing/loan policy, staff security, admission, inbox,
    # certification/reminder and offline-event capabilities (11 keys).
    assert len(FEATURE_DEFINITIONS) == 30
    assert FEATURE_WORKFLOWS["inventory.kiosk"] == ["kiosk", "kiosk_scanner"]


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
    # Staff invitations also stay available by default, including without the
    # community membership module; the staff security switch remains opt-in.
    assert default_enabled_features() == [
        "staff.invitations",
        "charges.enabled",
        "charges.bookings",
        "charges.events",
        "charges.machines",
        "charges.membership",
        "charges.loans",
        "inventory.self_checkout",
        "payments.enabled",
        "mobile.push",
        "presence.geofence",
    ]
    assert not any(
        key.startswith("payments.") and key != "payments.enabled"
        for key in default_enabled_features()
    )
    # The `charges.*` family is the deliberate exception to "dormant by default". It
    # decides whether money owed is RECORDED, not whether it can be collected, so it
    # cannot make an unconfigured space start charging anyone: the real trigger stays a
    # configured amount. Defaulting it off would reproduce the bug it exists to fix --
    # a space with no gateway silently losing every debt.
    assert all(
        key.startswith("charges.") for key in default_enabled_features()[1:7]
    )


def test_delegated_notification_recipients_default_off_and_match_the_frontend():
    from apps.makerspaces.capabilities import FEATURES

    definition = FEATURES["notifications.delegated_recipients"]
    assert definition.parent_module == "notifications"
    assert definition.default_enabled is False
    assert definition.key not in default_enabled_features()


