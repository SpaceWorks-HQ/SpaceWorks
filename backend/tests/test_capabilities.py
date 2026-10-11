"""Explicit collection barrel for capability defaults and behavior tests."""

from tests.capabilities_defaults import (
    test_kiosk_feature_is_standalone_default_off_and_advertises_two_workflows,
    test_feature_registry_rejects_unknown_duplicate_and_missing_dependencies,
    test_feature_defaults_are_dormant_except_legacy_compatible_self_checkout,
    test_delegated_notification_recipients_default_off_and_match_the_frontend,
)

from tests.capabilities_behavior import (
    test_self_checkout_is_standalone_and_independent_of_public_inventory,
    test_machine_payment_requires_machines_and_machine_service,
    test_a_payment_feature_without_the_payments_module_is_refused,
    test_effective_feature_requires_parent_and_typed_guard,
    test_model_and_admin_validator_share_printing_rule,
    test_feature_dependency_and_bootstrap_projection,
    test_staff_serializer_splits_module_and_feature_capability_writes,
    test_admin_form_rejects_child_without_parent_even_when_ui_is_bypassed,
    test_admin_form_allows_standalone_self_checkout_without_a_parent_module,
    test_admin_form_offers_every_registered_module_on_a_fresh_makerspace,
    test_admin_form_keeps_unrecognised_stored_module_keys_selectable,
    test_membership_payment_uses_the_registered_membership_module,
    test_membership_without_builtin_member_accounts_is_valid,
    test_frontend_feature_definitions_match_the_backend,
)


@pytest.mark.django_db
def test_saved_report_views_default_on_but_require_reports():
    from apps.makerspaces.platform import feature_enabled
    from tests.return_helpers import make_space
    from tests.module_helpers import disable_module

    space = make_space("saved-report-feature")
    assert feature_enabled(space, "reports.saved_views")
    disable_module(space, "reports")
    assert not feature_enabled(space, "reports.saved_views")
