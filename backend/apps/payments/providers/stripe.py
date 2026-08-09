"""Stripe, behind the provider protocol.

A thin adapter over the existing ``apps.payments.stripe_client``, not a rewrite. The
Stripe path is the one taking real money today, so this phase deliberately changes its
behaviour nowhere: the adapter translates the generic ``CheckoutRequest`` into exactly
the parameters ``_create_checkout_url_atomic`` was already sending, and hands the result
back in the generic shape.
"""

from apps.payments import stripe_client
from apps.payments.providers.base import (
    STRIPE,
    CheckoutRequest,
    CheckoutResult,
    PaymentsUnavailable,
    WebhookEvent,
    WebhookVerificationError,
)


def _value(value, key):
    """Stripe objects are attribute-accessed; the test doubles are plain dicts."""
    return value.get(key) if isinstance(value, dict) else getattr(value, key, None)


class StripeProvider:
    key = STRIPE

    def create_checkout(self, source, request: CheckoutRequest) -> CheckoutResult:
        params = {
            "mode": "payment",
            "client_reference_id": request.reference,
            "success_url": request.success_url,
            "cancel_url": request.cancel_url,
            "metadata": {key: str(value) for key, value in (request.metadata or {}).items()},
            "line_items": [
                {
                    "price_data": {
                        "currency": request.currency,
                        "unit_amount": request.amount_minor,
                        "product_data": {"name": request.description},
                    },
                    "quantity": 1,
                }
            ],
        }
        if request.application_fee_minor:
            params["payment_intent_data"] = {
                "application_fee_amount": request.application_fee_minor
            }
        session = stripe_client.create_checkout_session(
            source, idempotency_key=request.idempotency_key, **params
        )
        session_id, checkout_url = _value(session, "id"), _value(session, "url")
        if not session_id or not checkout_url:
            raise PaymentsUnavailable("Stripe did not return a Checkout URL.")
        return CheckoutResult(order_id=session_id, checkout_url=checkout_url)

    def expire_checkout(self, source, order_id: str) -> None:
        if not order_id:
            return
        stripe_client.expire_checkout_session(source, order_id)

    def verify_webhook(self, source, *, payload: bytes, headers) -> WebhookEvent:
        signature = headers.get("Stripe-Signature") or headers.get("HTTP_STRIPE_SIGNATURE", "")
        try:
            event = stripe_client.construct_event(payload, signature, source.webhook_secret)
        except Exception as exc:
            raise WebhookVerificationError("Stripe signature verification failed.") from exc
        event_type = _value(event, "type") or ""
        data = _value(event, "data") or {}
        obj = _value(data, "object") or {}
        return WebhookEvent(
            event_id=_value(event, "id") or "",
            # Both the synchronous and the delayed-settlement events, matching what
            # `apply_webhook_event` already settles. `checkout.session.completed` alone
            # is not enough: a bank-debit session completes before the money moves.
            is_paid=(
                event_type == "checkout.session.completed"
                and _value(obj, "payment_status") == "paid"
            )
            or event_type == "checkout.session.async_payment_succeeded",
            order_id=_value(obj, "id") or "",
            payment_id=_value(obj, "payment_intent") or "",
            metadata=_value(obj, "metadata") or {},
        )
