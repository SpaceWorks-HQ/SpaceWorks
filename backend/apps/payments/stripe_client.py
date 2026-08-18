"""Lazy Stripe integration helpers with no process-global credential mutation."""

from importlib import import_module

from apps.payments.models import MakerspacePaymentSettings
from apps.payments.resolution import PaymentSource, resolve_payment_source


class PaymentsUnavailable(Exception):
    """Raised when a payment operation cannot safely use Stripe."""


class StripeWebhookSignatureError(Exception):
    """Raised only when Stripe rejects a webhook signature."""


def _stripe_module():
    return import_module("stripe")


def _source(makerspace_or_settings):
    if isinstance(makerspace_or_settings, PaymentSource):
        return makerspace_or_settings
    if hasattr(makerspace_or_settings, "get_stripe_secret_key"):
        payment_settings = makerspace_or_settings
        if not payment_settings.raw_credentials_configured:
            return None
        try:
            return PaymentSource(
                "raw",
                payment_settings.get_stripe_secret_key(),
                payment_settings.get_stripe_webhook_secret(),
                publishable_key=payment_settings.stripe_publishable_key,
            )
        except Exception:
            return None
    return resolve_payment_source(makerspace_or_settings)


def build_client(makerspace_or_settings):
    """Build a fresh client for this request without setting ``stripe.api_key``."""
    source = _source(makerspace_or_settings)
    if source is None or not source.secret_key:
        raise PaymentsUnavailable("Stripe is not configured for this makerspace.")
    return _stripe_module().StripeClient(api_key=source.secret_key)


def create_checkout_session(
    makerspace_or_settings, *, idempotency_key=None, **params
):
    """Create a Checkout Session through a makerspace-specific client (for C.3)."""
    source = _source(makerspace_or_settings)
    if source is None:
        raise PaymentsUnavailable("Stripe is not configured for this makerspace.")
    options = {}
    if source.provider == "connect" and source.connected_account_id:
        options["stripe_account"] = source.connected_account_id
    if idempotency_key:
        options["idempotency_key"] = idempotency_key
    return build_client(source).v1.checkout.sessions.create(
        params=params, **({"options": options} if options else {})
    )


def create_payment_intent(makerspace_or_settings, *, idempotency_key, **params):
    source = _source(makerspace_or_settings)
    if source is None:
        raise PaymentsUnavailable('Stripe is not configured for this makerspace.')
    options = {'idempotency_key': idempotency_key}
    if source.provider == 'connect' and source.connected_account_id:
        options['stripe_account'] = source.connected_account_id
    return build_client(source).v1.payment_intents.create(
        params=params,
        options=options,
    )


def retrieve_payment_intent(makerspace_or_settings, intent_id):
    source = _source(makerspace_or_settings)
    if source is None:
        raise PaymentsUnavailable('Stripe is not configured for this makerspace.')
    options = {}
    if source.provider == 'connect' and source.connected_account_id:
        options['stripe_account'] = source.connected_account_id
    return build_client(source).v1.payment_intents.retrieve(
        intent_id,
        **({'options': options} if options else {}),
    )


def cancel_payment_intent(makerspace_or_settings, intent_id):
    """Return whether Stripe authoritatively canceled the PaymentIntent."""
    try:
        source = _source(makerspace_or_settings)
        if source is None:
            return False
        options = (
            {"stripe_account": source.connected_account_id}
            if source.provider == "connect" and source.connected_account_id
            else None
        )
        build_client(source).v1.payment_intents.cancel(
            intent_id, **({"options": options} if options else {})
        )
        return True
    except Exception:
        # Cancellation can race confirmation; retrieve before reporting failure.
        try:
            intent = retrieve_payment_intent(makerspace_or_settings, intent_id)
            status = intent.get("status") if isinstance(intent, dict) else intent.status
            return status == "canceled"
        except Exception:
            return False


def expire_checkout_session(makerspace_or_settings, session_id):
    """Return whether Stripe authoritatively expired the Checkout Session."""
    try:
        source = _source(makerspace_or_settings)
        if source is None:
            return False
        options = (
            {"stripe_account": source.connected_account_id}
            if source.provider == "connect" and source.connected_account_id
            else None
        )
        build_client(source).v1.checkout.sessions.expire(
            session_id, **({"options": options} if options else {})
        )
        return True
    except Exception:
        # Expiry can race natural closure; only an authoritative retrieve clears it.
        return checkout_session_is_closed(makerspace_or_settings, session_id)


def checkout_session_is_closed(makerspace_or_settings, session_id):
    """Return True only when Stripe authoritatively reports a closed session."""
    try:
        source = _source(makerspace_or_settings)
        if source is None:
            return False
        options = (
            {"stripe_account": source.connected_account_id}
            if source.provider == "connect" and source.connected_account_id
            else None
        )
        session = build_client(source).v1.checkout.sessions.retrieve(
            session_id, **({"options": options} if options else {})
        )
        status = session.get("status") if isinstance(session, dict) else session.status
        return status == "expired"
    except Exception:
        return False


def construct_event(payload, sig_header, webhook_secret):
    """Verify and parse a Stripe event without configuring a global API key."""
    if not webhook_secret:
        raise PaymentsUnavailable("Stripe webhook verification is not configured.")
    stripe = _stripe_module()
    try:
        return stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
    except Exception as exc:
        signature_errors = tuple(
            error
            for error in (
                getattr(stripe, "SignatureVerificationError", None),
                getattr(getattr(stripe, "error", None), "SignatureVerificationError", None),
            )
            if isinstance(error, type) and issubclass(error, Exception)
        )
        if signature_errors and isinstance(exc, signature_errors):
            raise StripeWebhookSignatureError("Invalid Stripe webhook signature.") from exc
        raise
