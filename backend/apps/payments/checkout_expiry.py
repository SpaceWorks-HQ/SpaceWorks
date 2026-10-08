"""One definition of "this hosted checkout is dead", shared by every path that learns it.

A hosted checkout is recorded twice on a Payment: the historic Stripe-shaped columns
(`stripe_checkout_session_id`, `stripe_checkout_url`) and the provider-agnostic ones
(`external_order_id`, `checkout_url`) added for the provider seam. The expiry webhook and
credential rotation used to clear only the Stripe pair, so the generic `checkout_url` kept
the expired link and `create_checkout_url` handed it back on every retry: once a session
expired, the member could never be given a working link again.
"""

from django.utils import timezone

#: Every column that names a live hosted page, plus the stamp that marks it closed.
CLOSED_CHECKOUT_FIELDS = [
    "stripe_checkout_session_expired_at",
    "stripe_checkout_session_id",
    "stripe_checkout_url",
    "external_order_id",
    "checkout_url",
]


def forget_closed_checkout(payment):
    """Clear a hosted page the provider has confirmed closed. Returns the fields to save.

    Never touches `status`, `amount` or `stripe_payment_intent_id`: the intent is what a
    refund of a settled charge is sent against, so it outlives the page that created it.
    """
    payment.stripe_checkout_session_expired_at = timezone.now()
    payment.stripe_checkout_session_id = None
    payment.stripe_checkout_url = ""
    payment.external_order_id = None
    payment.checkout_url = ""
    return list(CLOSED_CHECKOUT_FIELDS)


def live_checkout_url(payment):
    """The hosted link a member may still pay, from whichever rail raised it, or ""."""
    if payment.status != payment.Status.PENDING or payment.stripe_checkout_session_expired_at:
        return ""
    return payment.checkout_url or payment.stripe_checkout_url or ""
