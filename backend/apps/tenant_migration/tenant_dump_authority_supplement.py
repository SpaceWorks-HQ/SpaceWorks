"""Credential, provider-binding and regenerated-token Lane D field rules."""

from .tenant_dump_types import AuthorityDisposition as D
from .tenant_dump_types import authority
from .tenant_dump_authority_devices import DEVICE_AUTHORITY_ENTRIES
from .tenant_dump_authority_7c import LABEL_AUTHORITY_ENTRIES


def _same(label, names, disposition, reason):
    return tuple(
        ((label, name), authority(disposition, reason)) for name in names.split()
    )


SUPPLEMENTAL_AUTHORITY_ENTRIES = (
    *_same("payments.MakerspaceBillingSettings", "payment_terms_days", D.PRESERVE,
           "New-charge terms are tenant policy; imported charges keep their snapshotted due dates."),
    *_same("payments.MakerspaceBillingSettings", "reminder_days_before reminder_days_after max_reminders", D.RESET,
           "Automatic member mail requires target opt-in; a portable archive cannot enable reminders."),
    *_same("payments.Payment", "due_at", D.PRESERVE,
           "The original due date travels with the money owed."),
    *_same(
        "makerspaces.Makerspace", "timezone country opening_hours", D.PRESERVE,
        "The tenant location and advisory wall-clock schedule travel unchanged.",
    ),
    *_same(
        "hardware_requests.ReplayCommand",
        "id makerspace station actor operator_lease_id station_session_id station_version "
        "client_command_id payload_fingerprint operation_kind operation_version aggregate_id "
        "sequence predecessor state claim_token claimed_at claim_attempts client_created_at "
        "expires_at created_at updated_at completed_at failure_code failure_detail "
        "subject_request subject_loan evidence result_request result_loan result_return_event "
        "resolution_code resolved_by resolved_at replacement_command",
        D.DROP,
        "Replay ownership and claims are source-local coordination and never travel.",
    ),
    *_same(
        "makerspaces.Station",
        "created_by",
        D.RESET,
        "Source provisioning provenance cannot assign a target User.",
    ),
    *_same(
        "makerspaces.StationCredential",
        "id station public_token pin_digest pin_ciphertext version is_enabled rotated_at "
        "disabled_at created_at updated_at",
        D.DROP,
        "Live Station credentials never travel in a portable tenant archive.",
    ),
    *_same(
        "makerspaces.StationOperatorLease",
        "id makerspace station actor station_session_id station_version allowed_actions "
        "issued_at expires_at revoked_at",
        D.DROP,
        "Kiosk operator leases are live session authority and never travel.",
    ),
    *_same(
        "makerspaces.StationSessionRevocation",
        "session_id station expires_at created_at",
        D.DROP,
        "Session revocations only deny source-local sessions that cannot travel.",
    ),
    *_same(
        "bookings.Booking",
        "public_token",
        D.RESET,
        "Source booking bearer tokens are regenerated.",
    ),
    *_same(
        "hardware_requests.HardwareRequest",
        "public_token",
        D.RESET,
        "Source lending status tokens are regenerated.",
    ),
    *_same(
        "machines.MachineServiceRequest",
        "public_token",
        D.RESET,
        "Source machine-service status tokens are regenerated.",
    ),
    *_same(
        "payments.MakerspacePaymentSettings",
        "provider stripe_publishable_key stripe_secret_key stripe_webhook_secret "
        "connect_account_id connect_status connect_charges_enabled connect_payouts_enabled "
        "connect_account_assigned_at connect_status_updated_at razorpay_key_id "
        "razorpay_key_secret razorpay_webhook_secret",
        D.RESET,
        "Source provider selection, credentials and account bindings do not travel live.",
    ),
    *_same(
        "payments.Payment",
        "status amount currency provider subject_type subject_id subject_label",
        D.PRESERVE,
        "Terminal payment history remains readable; pending payments refuse the build.",
    ),
    *_same(
        "payments.Payment",
        "via_makerspace external_order_id external_payment_id checkout_url stripe_provider "
        "stripe_connected_account_id stripe_application_fee_amount online_rail "
        "stripe_checkout_session_id stripe_checkout_url stripe_checkout_session_expired_at "
        "stripe_payment_intent_id",
        D.RESET,
        "Provider handles and cross-tenant routing cannot authorize target operations.",
    ),
    *_same(
        "payments.ManualSettlement",
        "method reference received_at amount currency",
        D.PRESERVE,
        "The cash book travels with the payments it explains: how and when money was "
        "taken is the space's own record, not a provider handle.",
    ),
    *_same(
        "payments.Refund",
        "status amount currency provider reason method reference refunded_at",
        D.PRESERVE,
        "Refund history remains readable alongside the payment it corrects.",
    ),
    *_same(
        "payments.Refund",
        "external_refund_id",
        D.RESET,
        "Provider refund handles cannot authorize target operations.",
    ),
    *_same(
        "makerspaces.MemberCard",
        "printed_name photo_object_key photo_content_type photo_size_bytes photo_consent_at "
        "photo_consent_version",
        (D.PRESERVE, D.DROP),
        "Full-user card identity travels; stub-linked identity content does not.",
    ),
    # Membership plans, terms and invitation requests (forward plan phase 6).
    *_same(
        "makerspaces.InvitationRequest",
        "name email phone message",
        (D.PRESERVE, D.DROP),
        "A lead's contact details travel with a full tenant; stub-linked content does not.",
    ),
    *_same(
        "makerspaces.InvitationRequest",
        "status",
        D.PRESERVE,
        "Whether a lead was invited or declined is honest history, not authority.",
    ),
    *_same(
        "makerspaces.MembershipPlan",
        "is_active",
        D.PRESERVE,
        "Which plans a tenant still sells is its own pricing choice.",
    ),
    *_same(
        "makerspaces.MembershipTerm",
        "status",
        D.PRESERVE,
        "Term history stays readable; it never changes membership authority.",
    ),
    # Abandoned-upload cleanup (forward plan phase 11): source policy and source
    # consumption proof never authorize an irreversible deletion on the target.
    *_same(
        "evidence.EvidenceRetentionPolicy",
        "abandoned_upload_cleanup_enabled abandoned_upload_retention_days",
        D.RESET,
        "Irreversible abandoned-upload cleanup is target-owned policy.",
    ),
    *_same(
        "evidence.EvidencePhoto",
        "consumption_state",
        D.RESET,
        "Imported photos are legacy-unknown: a source marker is not target cleanup proof.",
    ),
    *_same(
        "makerspaces.Makerspace",
        "lapsed_members_cannot_borrow",
        D.PRESERVE,
        "A tenant's own borrowing rule for lapsed members, still bounded by target modules.",
    ),
    *DEVICE_AUTHORITY_ENTRIES,
    *LABEL_AUTHORITY_ENTRIES,
)
