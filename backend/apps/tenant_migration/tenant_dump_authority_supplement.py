"""Credential, provider-binding and regenerated-token Lane D field rules."""

from .tenant_dump_types import AuthorityDisposition as D
from .tenant_dump_types import authority


def _same(label, names, disposition, reason):
    return tuple(
        ((label, name), authority(disposition, reason)) for name in names.split()
    )


SUPPLEMENTAL_AUTHORITY_ENTRIES = (
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
        "payments.Refund",
        "status amount currency provider reason",
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
    *_same(
        "makerspaces.Makerspace",
        "lapsed_members_cannot_borrow",
        D.PRESERVE,
        "A tenant's own borrowing rule for lapsed members, still bounded by target modules.",
    ),
)
