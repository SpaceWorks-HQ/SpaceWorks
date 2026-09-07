from apps.makerspaces.platform import feature_enabled, module_enabled
from apps.payments.resolution import resolve_payment_source


def online_payments_enabled(makerspace, domain):
    """Whether this makerspace may accept online payments for a domain.

    Every clause here is an additive AND, never a replacement, so turning any one of
    them on can never make an unconfigured space start charging:

    * the `payments` MODULE ships the surfaces at all (phase 3),
    * `payments.enabled` is the space manager's master switch in front of them (A6),
    * the per-domain feature says which domains may charge,
    * and credentials must actually resolve.

    Uninstalling the module stops new charges without touching stored credentials or
    any existing Payment row -- and it deliberately does NOT reach the webhook, which
    settles a real charge regardless, because money already taken must never be
    stranded by a toggle.
    """
    return (
        module_enabled(makerspace, "payments")
        and feature_enabled(makerspace, "payments.enabled")
        and feature_enabled(makerspace, f"payments.{domain}")
        and resolve_payment_source(makerspace) is not None
    )


def charge_tracking_enabled(makerspace, domain):
    """Whether a debt in this domain is RECORDED at all.

    Deliberately shorter than `online_payments_enabled` above: no module clause and no
    credential clause. Knowing that a member owes money is not the same capability as
    being able to take it from them online, and conflating the two is what made cash-only
    spaces lose the debt entirely -- no pending row, nothing to settle, nothing in
    reports.

    So this governs whether the charge exists; `online_payments_enabled` governs only
    whether a Stripe/Razorpay rail is put behind it. A space with the `payments` module
    uninstalled still tracks and settles money by hand.

    `charges.enabled` is the master switch and is checked ONLY here -- it is not a
    `requires_features` edge on the domain keys, which would make it un-flippable until
    every domain was unticked first (the same A6 rule the payments master switch follows).
    """
    # No tombstone clause here any more. The ledger surfaces -- member history,
    # reconciliation, receipts -- are permanently core since the rail was split into
    # `apps.payments_rail`, so a recorded debt is always readable and settleable by
    # someone. Tombstoning only removes the ability to pay it by card.
    return (
        feature_enabled(makerspace, "charges.enabled")
        and feature_enabled(makerspace, f"charges.{domain}")
    )


#: Which capability domain each payment subject belongs to. Kept beside the two
#: predicates so a new SubjectType cannot quietly acquire a rail nobody switched on.
SUBJECT_DOMAINS = {
    "machine_service_request": "machines",
    "booking": "bookings",
    "event_registration": "events",
    "makerspace_membership": "membership",
    "membership_term": "membership",
    "loan_deposit": "loans",
    "loan_late_fee": "loans",
}


def online_payments_enabled_for(payment):
    """Whether an online rail may be raised for THIS charge.

    The member checkout and native payment-intent endpoints both create provider objects
    directly, so without this an unclaimed cash-only debt could still mint a live payment
    link from a space that has switched its rail off -- or has none at all.
    """
    domain = SUBJECT_DOMAINS.get(payment.subject_type)
    if domain is None:
        return False
    return online_payments_enabled(payment.makerspace, domain)
