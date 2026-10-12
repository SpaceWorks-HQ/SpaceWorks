"""Closing a live online rail when staff settle a charge another way.

Split out of `reconciliation.py` at the 300-line ceiling.
"""

import logging

from django.utils import timezone

from apps.payments import stripe_client
from apps.payments.models import Payment
from apps.payments.resolution import source_for_payment

logger = logging.getLogger(__name__)


def _expire_checkout_best_effort(payment):
    """Close a live online rail when staff settle a charge another way.

    Without this a member can still pay a hosted link or confirm a native PaymentIntent
    for a charge already marked offline or waived. Best-effort by contract: the
    reconciliation that called this must succeed regardless of what the vendor says.
    """
    if (
        payment.online_rail == Payment.OnlineRail.NATIVE_PAYMENT_INTENT
        and payment.stripe_payment_intent_id
    ):
        try:
            source = source_for_payment(payment)
            if source is None:
                raise stripe_client.PaymentsUnavailable(
                    "The payment's provider credentials are no longer configured."
                )
            if not stripe_client.cancel_payment_intent(
                source, payment.stripe_payment_intent_id
            ):
                logger.warning(
                    "payment_intent_cancellation_unconfirmed",
                    extra={"payment_id": payment.pk},
                )
        except Exception:
            logger.exception(
                "payment_intent_cancellation_failed",
                extra={"payment_id": payment.pk},
            )
        return

    order_id = payment.external_order_id or payment.stripe_checkout_session_id
    if not order_id or payment.stripe_checkout_session_expired_at:
        return
    try:
        source = source_for_payment(payment)
        if source is None:
            raise stripe_client.PaymentsUnavailable(
                "The payment's provider credentials are no longer configured."
            )
        if payment.provider != payment.Provider.STRIPE:
            from apps.payments.providers import get_provider

            get_provider(payment.provider).expire_checkout(source, order_id)
            payment.stripe_checkout_session_expired_at = timezone.now()
        elif stripe_client.expire_checkout_session(source, order_id):
            payment.stripe_checkout_session_expired_at = timezone.now()
    except Exception:
        logger.exception(
            "payment_checkout_expiry_failed", extra={"payment_id": payment.pk}
        )
