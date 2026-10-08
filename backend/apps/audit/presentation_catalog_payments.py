"""Presentation entries: Payment, payment-rail and member-card audit actions.

Generated from the audit AST discovery, then reviewed. Every literal action has one
entry; ``permitted`` lists only reviewed non-personal LEAF paths (no names, free
text, secrets, object keys or before/after payloads)."""

from .presentation_catalog_types import P

ENTRIES = (
    P("member_card.created", "Member card created", ("card_id",)),
    P("member_card.issued", "Member card issued", ("card_id",)),
    P("member_card.name_updated", "Member card name updated", ("card_id",)),
    P("member_card.photo_removed", "Member card photo removed", ("card_id",)),
    P("member_card.photo_updated", "Member card photo updated", ("card_id",)),
    P("member_card.printed", "Member card printed", ("card_id", "count")),
    P("member_card.reissued", "Member card reissued", ("card_id",)),
    P("member_card.revoked", "Member card revoked", ("card_id",)),
    P("member_card.scanned", "Member card scanned", ("outcome", "qr_id")),
    P("member_card.template_updated", "Member card template updated", ("version",)),
    P("payment.canceled", "Payment canceled"),
    P("payment.checkout_created", "Payment checkout created",
      ("payment_id", "provider", "subject_id", "subject_type")),
    P("payment.checkout_expired", "Payment checkout expired", ("stripe_event_id",)),
    P("payment.created", "Payment created",
      ("amount", "currency", "payment_id", "subject_id", "subject_type", "via_makerspace_id")),
    P("payment.double_paid_refund_required", "Payment double paid refund required",
      ("event_id", "prior_status", "provider", "stripe_event_id")),
    P("payment.mobile_intent_created", "Payment mobile intent created", ("stripe_provider",)),
    P("payment.paid_after_terminal", "Payment paid after terminal",
      ("event_id", "prior_status", "provider", "resolved_status", "stripe_event_id")),
    P("payment.paid_offline", "Payment paid offline"),
    P("payment.paid_online", "Payment paid online",
      ("event_id", "provider", "stripe_event_id")),
    P("payment.refund_failed", "Payment refund failed"),
    P("payment.refund_requested", "Payment refund requested",
      ("amount", "payment_id", "refund_id")),
    P("payment.refunded", "Payment refunded"),
    P("payment.settlement_amended", "Payment settlement amended",
      ("amends_id", "method", "previous_method", "settlement_id")),
    P("payment.waived", "Payment waived"),
    P("payments.connect_account_mapped", "Payments connect account mapped"),
    P("payments.connect_authorization_revoked", "Payments connect authorization revoked"),
    P("payments.connect_callback_consumed", "Payments connect callback consumed"),
    P("payments.connect_deauthorization_ignored", "Payments connect deauthorization ignored"),
    P("payments.connect_deauthorized", "Payments connect deauthorized"),
    P("payments.connect_onboarded", "Payments connect onboarded"),
    P("payments.connect_onboarding_started", "Payments connect onboarding started"),
    P("payments.connect_previous_authorization_revoked", "Payments connect previous authorization revoked",
      ),
    P("payments.connect_status_update_ignored", "Payments connect status update ignored"),
    P("payments.connect_status_updated", "Payments connect status updated"),
    P("payments.settings_updated", "Payments settings updated"),
)
