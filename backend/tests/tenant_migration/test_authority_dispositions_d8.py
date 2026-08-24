"""Literal §3a disposition contract; this must not derive expectations from code."""

import pytest

from apps.tenant_migration.tenant_dump_authority import AUTHORITY_FIELD_OVERRIDES
from apps.tenant_migration.tenant_dump_catalog import FIELD_POLICIES
from apps.tenant_migration.tenant_dump_types import AuthorityDisposition as D


def _fields(label, names, dispositions):
    if not isinstance(dispositions, tuple):
        dispositions = (dispositions,)
    return [((label, name), dispositions) for name in names.split()]


EXPECTED = dict(
    [
        *_fields("accounts.User", "is_superuser is_staff role", D.RESET),
        *_fields("accounts.User", "groups user_permissions", D.DROP),
        *_fields(
            "accounts.User",
            "telegram_user_id external_checkin_user_id",
            D.RESET,
        ),
        *_fields("accounts.User", "is_tenant_dump_stub", D.PRESERVE),
        *_fields(
            "accounts.User",
            "id username password email phone phone_e164 phone_verified_at "
            "email_verified_at is_active access_status must_change_password is_walk_in",
            (D.PRESERVE, D.RESET),
        ),
        *_fields(
            "makerspaces.MakerspaceMembership",
            "status verified_at activated_at revoked_at revocation_reason "
            "waiver_accepted_at waiver_version_accepted accepted_waiver "
            "witnessed_waiver witnessed_waiver_version witnessed_at",
            D.PRESERVE,
        ),
        *_fields(
            "makerspaces.MakerspaceMembership",
            "role assigned_role can_refer can_verify receives_notifications",
            D.RESET,
        ),
        *_fields("makerspaces.MembershipRequest", "state", (D.PRESERVE, D.DROP)),
        *_fields(
            "makerspaces.MembershipRequest",
            "assigned_role auto_activate_on_claim",
            D.RESET,
        ),
        *_fields(
            "makerspaces.Makerspace",
            "membership_policy referrals_enabled superadmin_access_enabled "
            "frontend_domain frontend_domain_status domain_verification_token "
            "domain_verified_at frontend_domain_changed_at cors_allowed_origins "
            "enabled_modules enabled_features resource_limit_overrides "
            "hidden_from_central_directory storage_bytes_used archived_at archived_by "
            "lifecycle_state staff_notifications_enabled "
            "booking_requester_notifications_enabled public_api_key smtp_host smtp_port "
            "smtp_username smtp_password smtp_use_tls smtp_use_ssl smtp_from_email "
            "telegram_group_chat_id telegram_bot_token slack_webhook_url "
            "mattermost_webhook_url discord_webhook_url",
            D.RESET,
        ),
        *_fields(
            "makerspaces.Makerspace",
            "public_inventory_enabled public_stats_enabled "
            "public_stats_show_holder_names public_print_status_lookup_policy",
            D.PRESERVE,
        ),
        *_fields(
            "inventory.InventoryProduct",
            "is_public show_public_count public_availability_mode is_archived",
            D.PRESERVE,
        ),
        *_fields(
            "inventory.InventoryProduct", "public_self_checkout_enabled", D.RESET
        ),
        *_fields(
            "inventory.InventoryAsset", "public_self_checkout_enabled", D.RESET
        ),
        *_fields("machines.Machine", "is_public is_active", D.PRESERVE),
        *_fields("machines.Machine", "camera_feed_url", D.RESET),
        *_fields("machines.MachineType", "managing_action", D.RESET),
        *_fields(
            "machines.MachineOperator",
            "id machine user access_level assigned_by assigned_at",
            D.PRESERVE,
        ),
        *_fields(
            "bookings.BookableSpace",
            "is_public show_public_availability show_public_booker_names is_active",
            D.PRESERVE,
        ),
        *_fields(
            "bookings.BookableSpace",
            "approval_mode requester_notifications_enabled public_token",
            D.RESET,
        ),
        *_fields("bookings.Booking", "public_token", D.RESET),
        *_fields("events.Event", "is_public status", D.PRESERVE),
        *_fields("events.Event", "public_token", D.RESET),
        *_fields(
            "events.EventRegistration",
            "checkin_token registered_via_makerspace payment_via_makerspace",
            D.RESET,
        ),
        *_fields(
            "makerspaces.MemberProfile",
            "is_visible show_attended_events headline institution bio avatar_key "
            "interests languages education github_username github_contributions "
            "github_synced_at",
            (D.PRESERVE, D.DROP),
        ),
        *_fields(
            "makerspaces.MemberProject",
            "id profile title description image_key links position created_at updated_at",
            (D.PRESERVE, D.DROP),
        ),
        *_fields(
            "integrations.NotificationDestination",
            "channel telegram_chat_id",
            (D.PRESERVE, D.DROP),
        ),
        *_fields("integrations.NotificationDestination", "is_active", D.RESET),
        *_fields("integrations.NotificationDestination", "webhook_url", D.DROP),
        *_fields(
            "integrations.DestinationCategoryScope",
            "id destination category",
            (D.PRESERVE, D.DROP),
        ),
        *_fields(
            "integrations.DestinationMachineScope",
            "id destination machine",
            (D.PRESERVE, D.DROP),
        ),
        *_fields(
            "integrations.DestinationMachineTypeScope",
            "id destination machine_type",
            (D.PRESERVE, D.DROP),
        ),
        *_fields(
            "integrations.EmailTemplate", "subject text_body html_body is_active", D.PRESERVE
        ),
        *_fields(
            "integrations.MachineTypeEmailTemplate",
            "subject text_body html_body is_active",
            D.PRESERVE,
        ),
        *_fields("integrations.ChatTemplate", "text_body is_active", D.PRESERVE),
        *_fields(
            "backup.MakerspaceArchiveRecipient",
            "public_recipient fingerprint label",
            D.PRESERVE,
        ),
        *_fields(
            "backup.MakerspaceArchiveRecipient",
            "verified_at challenge_nonce_digest challenge_issued_at",
            D.RESET,
        ),
        *_fields("apiclients.ApiKeyRequest", "status", (D.PRESERVE, D.DROP)),
        *_fields(
            "hardware_requests.HardwareRequest", "public_token", D.RESET
        ),
        *_fields("machines.MachineServiceRequest", "public_token", D.RESET),
        *_fields(
            "payments.MakerspacePaymentSettings",
            "provider stripe_publishable_key stripe_secret_key stripe_webhook_secret "
            "connect_account_id connect_status connect_charges_enabled "
            "connect_payouts_enabled connect_account_assigned_at "
            "connect_status_updated_at razorpay_key_id razorpay_key_secret "
            "razorpay_webhook_secret",
            D.RESET,
        ),
        *_fields(
            "payments.Payment",
            "status amount currency provider subject_type subject_id subject_label",
            D.PRESERVE,
        ),
        *_fields(
            "payments.Payment",
            "via_makerspace external_order_id external_payment_id checkout_url "
            "stripe_provider stripe_connected_account_id stripe_application_fee_amount "
            "online_rail stripe_checkout_session_id stripe_checkout_url "
            "stripe_checkout_session_expired_at stripe_payment_intent_id",
            D.RESET,
        ),
        *_fields("audit.AuditLog", "event_uuid row_mac", D.RESET),
    ]
)


@pytest.mark.parametrize("edge, expected", EXPECTED.items())
def test_every_section_3a_field_has_its_exact_literal_disposition(edge, expected):
    assert FIELD_POLICIES[edge].dispositions == expected


def test_literal_section_3a_matrix_covers_every_authority_override_exactly_once():
    assert set(EXPECTED) == set(AUTHORITY_FIELD_OVERRIDES)


@pytest.mark.parametrize(
    "model_label",
    (
        "accounts.NativeAppRegistration",
        "apiclients.ApiClient",
        "integrations.EmailNotificationMute",
        "integrations.NotificationPreference",
        "integrations.NotificationRecipient",
        "integrations.RecipientCategoryScope",
        "integrations.RecipientMachineScope",
        "integrations.RecipientMachineTypeScope",
        "machines.RoleMachineScope",
        "machines.RoleMachineTypeScope",
        "makerspaces.MakerspaceRole",
        "makerspaces.SubdomainRequest",
        "organizations.Organization",
        "organizations.OrganizationMakerspace",
        "organizations.OrganizationMembership",
        "events.EventOrganizer",
    ),
)
def test_every_section_3a_drop_row_has_only_drop_field_dispositions(model_label):
    rules = [
        rule for (label, _field), rule in FIELD_POLICIES.items() if label == model_label
    ]
    assert rules
    assert all(rule.dispositions == (D.DROP,) for rule in rules)
