"""Target-side reconstruction rules for fields omitted from PORTABLE archives."""

from enum import StrEnum


class OmittedFieldDisposition(StrEnum):
    """Closed importer contract for a source field that has no archived value.

    FRESH means generate through the field's callable, retry collisions, and verify
    uniqueness again immediately before commit. DERIVED values come from target-owned
    state; DROP_ROW and QUARANTINE never insert the source row as an actionable row.
    """

    DROP_ROW = "drop_row"
    FRESH = "fresh"
    EMPTY_STRING = "empty_string"
    NULL = "null"
    DERIVED = "derived"
    QUARANTINE = "quarantine"


DROP_ROW = OmittedFieldDisposition.DROP_ROW
FRESH = OmittedFieldDisposition.FRESH
EMPTY_STRING = OmittedFieldDisposition.EMPTY_STRING
NULL = OmittedFieldDisposition.NULL
DERIVED = OmittedFieldDisposition.DERIVED
QUARANTINE = OmittedFieldDisposition.QUARANTINE


def _rules(disposition, *fields):
    return {field: disposition for field in fields}


OMITTED_FIELD_RECONSTRUCTIONS = {
    **_rules(
        DROP_ROW,
        ("apiclients.ApiClient", "client_id"),
        ("apiclients.ApiClient", "secret_encrypted"),
        # Webhook destinations cannot satisfy their credential check constraint after
        # the encrypted webhook is removed, even when the source row is inactive.
        ("integrations.NotificationDestination", "webhook_url"),
    ),
    **_rules(
        FRESH,
        ("bookings.BookableSpace", "public_token"),
        ("bookings.Booking", "public_token"),
        ("events.Event", "public_token"),
        # Deliberately invalidate source event check-in QR codes at the trust boundary.
        ("events.EventRegistration", "checkin_token"),
        ("hardware_requests.HardwareRequest", "public_token"),
        ("machines.MachineServiceRequest", "public_token"),
        ("makerspaces.Makerspace", "public_api_key"),
    ),
    **_rules(
        DERIVED,
        ("events.EventRegistration", "email_exact_hash"),
        ("events.EventRegistration", "email_hash_generation"),
        # Unlike public_api_key, this callable-generated field has no database
        # uniqueness contract, so it cannot use the collision-checked FRESH rule.
        ("makerspaces.Makerspace", "domain_verification_token"),
        # The importer owns this outright: the row is created IMPORTING and only the
        # activation transition may make it ACTIVE, so no archived value may travel.
        ("makerspaces.Makerspace", "lifecycle_state"),
    ),
    **_rules(
        EMPTY_STRING,
        ("machines.Machine", "camera_feed_url"),
        ("makerspaces.Makerspace", "telegram_bot_token"),
        ("makerspaces.Makerspace", "smtp_password"),
        ("makerspaces.Makerspace", "slack_webhook_url"),
        ("makerspaces.Makerspace", "mattermost_webhook_url"),
        ("makerspaces.Makerspace", "discord_webhook_url"),
        ("payments.MakerspacePaymentSettings", "stripe_publishable_key"),
        ("payments.MakerspacePaymentSettings", "stripe_secret_key"),
        ("payments.MakerspacePaymentSettings", "stripe_webhook_secret"),
        ("payments.MakerspacePaymentSettings", "razorpay_key_id"),
        ("payments.MakerspacePaymentSettings", "razorpay_key_secret"),
        ("payments.MakerspacePaymentSettings", "razorpay_webhook_secret"),
        ("payments.Payment", "checkout_url"),
        ("payments.Payment", "stripe_checkout_url"),
    ),
    **_rules(
        NULL,
        ("machines.Machine", "legacy_print_printer_id"),
        ("machines.MachineConsumableAdjustment", "legacy_filament_adjustment_id"),
        ("machines.MachineConsumablePool", "legacy_filament_spool_id"),
        ("machines.MachineServiceRequest", "legacy_print_request_id"),
        ("machines.MachineUsageEntry", "legacy_manual_print_log_id"),
        ("machines.ServiceQueue", "legacy_print_bucket_id"),
        ("machines.ServiceRequestFile", "legacy_print_request_file_id"),
        ("payments.MakerspacePaymentSettings", "connect_account_id"),
        ("payments.Payment", "external_order_id"),
        ("payments.Payment", "external_payment_id"),
        ("payments.Payment", "stripe_connected_account_id"),
        ("payments.Payment", "stripe_checkout_session_id"),
        ("payments.Payment", "stripe_checkout_session_expired_at"),
        ("payments.Payment", "stripe_payment_intent_id"),
    ),
}
