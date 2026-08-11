"""Payment checkout boundary and compatibility exports."""

import logging
from decimal import Decimal, ROUND_HALF_UP
from django.db import transaction
from apps.makerspaces.platform import member_area_url
from apps.payments import stripe_client
from apps.payments.connect import refresh_connected_account, restrict_account_status
from apps.payments.models import (
    MakerspacePaymentSettings,
    Payment,
    PlatformStripeConnectSettings,
)
from apps.payments.resolution import resolve_payment_source, source_for_payment
from apps.payments.subjects import resolve_subject_labels, subject_label
from apps.payments.services_webhooks import (
    apply_connect_webhook_event,
    apply_razorpay_webhook_event,
    apply_webhook_event,
)

logger = logging.getLogger(__name__)


class _ConnectAccountCannotCharge(Exception):
    def __init__(self, merchant_id):
        self.merchant_id = merchant_id


class PaymentRailConflict(Exception):
    pass


def create_payment(
    *, makerspace, subject_type, subject_id, member, amount, currency, created_by,
    via_makerspace=None,
):
    source = resolve_payment_source(makerspace)
    if source is None:
        raise stripe_client.PaymentsUnavailable(
            "Payments are not configured for this makerspace."
        )
    provider = source.provider
    connected_account_id = source.connected_account_id
    fee_amount = _application_fee_amount(amount, source.application_fee_bps)
    return Payment.objects.create(
        makerspace=makerspace,
        subject_type=subject_type,
        subject_id=subject_id,
        member=member,
        via_makerspace=via_makerspace,
        amount=amount,
        currency=currency.lower(),
        created_by=created_by,
        # Stamped at creation from whatever resolved NOW, and immutable thereafter: a
        # space that switches vendor must still settle and expire the charges it raised
        # under the old one, and moving a row between vendors would point it at a
        # merchant account that never took the money.
        provider=source.vendor,
        stripe_provider=provider,
        stripe_connected_account_id=connected_account_id,
        stripe_application_fee_amount=fee_amount,
    )


def create_checkout(payment):
    """Schedule checkout creation; Stripe failure is deliberately never caller-visible."""
    transaction.on_commit(lambda: _create_checkout_safely(payment.pk))


def _create_checkout_safely(payment_id):
    try:
        create_checkout_url(payment_id)
    except Exception:
        logger.exception("payment_checkout_creation_failed", extra={"payment_id": payment_id})


def create_checkout_url(payment_id):
    """Create and persist a pending payment's Checkout URL exactly once."""
    try:
        return _create_checkout_url_atomic(payment_id)
    except _ConnectAccountCannotCharge as exc:
        merchant = MakerspacePaymentSettings.objects.get(pk=exc.merchant_id)
        restrict_account_status(merchant)
        raise stripe_client.PaymentsUnavailable(
            "Stripe Connect account cannot accept charges."
        ) from None


def _create_checkout_url_atomic(payment_id):
    payment_snapshot = Payment.objects.only(
        "makerspace_id", "stripe_provider"
    ).get(pk=payment_id)
    with transaction.atomic():
        # Checkout lock order is platform settings (Connect only) -> makerspace
        # settings -> Payment. Credential updates take their corresponding
        # settings lock before checking Payment rows. Payment-only reconciliation
        # must never acquire either settings lock, keeping the order acyclic.
        if payment_snapshot.stripe_provider == Payment.StripeProvider.CONNECT:
            platform = (
                PlatformStripeConnectSettings.objects.select_for_update()
                .filter(pk=1)
                .first()
            )
            if platform is None:
                raise stripe_client.PaymentsUnavailable(
                    "Stripe Connect is not configured."
                )
        merchant = (
            MakerspacePaymentSettings.objects.select_for_update()
            .filter(makerspace_id=payment_snapshot.makerspace_id)
            .first()
        )
        payment = Payment.objects.select_for_update().select_related("makerspace").get(pk=payment_id)
        if payment.status != Payment.Status.PENDING:
            return ""
        if payment.online_rail == Payment.OnlineRail.NATIVE_PAYMENT_INTENT:
            raise PaymentRailConflict('The payment already uses the native payment rail.')
        # Generic column first: a Razorpay row never fills the Stripe one, and without
        # this the service would mint a fresh payment link on every call -- several live
        # links for one charge, any of which a member could pay.
        if payment.checkout_url or payment.stripe_checkout_url:
            return payment.checkout_url or payment.stripe_checkout_url
        if payment.online_rail is None:
            payment.online_rail = Payment.OnlineRail.CHECKOUT
        source = source_for_payment(payment)
        if source is None:
            raise stripe_client.PaymentsUnavailable("Payments are not configured.")
        if payment.stripe_provider == Payment.StripeProvider.CONNECT:
            if (
                merchant is None
                or merchant.connect_account_id
                != payment.stripe_connected_account_id
            ):
                raise stripe_client.PaymentsUnavailable(
                    "Stripe Connect account is unavailable."
                )
            refreshed = refresh_connected_account(merchant)
            if not (
                refreshed.connect_status == MakerspacePaymentSettings.ConnectStatus.ACTIVE
                and refreshed.connect_charges_enabled
            ):
                raise _ConnectAccountCannotCharge(refreshed.pk)
        member_url = member_area_url(payment.makerspace)
        if not member_url:
            logger.warning("payment_checkout_return_url_unavailable", extra={"payment_id": payment_id})
            raise stripe_client.PaymentsUnavailable("A payment return URL is not configured.")
        label = subject_label(payment, resolve_subject_labels([payment]))
        if payment.provider != Payment.Provider.STRIPE:
            # Non-Stripe rows go through the provider seam. The Stripe branch below is
            # left untouched on purpose: it is the path taking real money today, and
            # this phase must not change its behaviour to add a second vendor.
            return _create_checkout_via_provider(payment, source, label, member_url)
        checkout_params = {
            "mode": "payment",
            "client_reference_id": str(payment.pk),
            "success_url": f"{member_url}?checkout=success",
            "cancel_url": f"{member_url}?checkout=cancelled",
            "metadata": {"payment_id": str(payment.pk), "makerspace_id": str(payment.makerspace_id)},
            "line_items": [{"price_data": {"currency": payment.currency, "unit_amount": int(payment.amount * 100), "product_data": {"name": label}}, "quantity": 1}],
        }
        if payment.stripe_application_fee_amount:
            checkout_params["payment_intent_data"] = {
                "application_fee_amount": payment.stripe_application_fee_amount
            }
        session = stripe_client.create_checkout_session(
            source,
            idempotency_key=_checkout_idempotency_key(payment),
            **checkout_params,
        )
        session_id, checkout_url = _value(session, "id"), _value(session, "url")
        if not session_id or not checkout_url:
            raise stripe_client.PaymentsUnavailable("Stripe did not return a Checkout URL.")
        payment.stripe_checkout_session_id = session_id
        payment.stripe_checkout_url = checkout_url
        payment.stripe_checkout_session_expired_at = None
        # Written in step with the historic columns. Migration 0010 backfilled existing
        # rows for the same reason: a checkout only the Stripe-shaped columns know about
        # is invisible to every provider-agnostic path added from here on.
        payment.external_order_id = session_id
        payment.checkout_url = checkout_url
        payment.save(
            update_fields=[
                "stripe_checkout_session_id",
                "stripe_checkout_url",
                "stripe_checkout_session_expired_at",
                "external_order_id",
                "checkout_url",
                "online_rail",
                "updated_at",
            ]
        )
        return checkout_url


def _create_checkout_via_provider(payment, source, label, member_url):
    """Raise a hosted page through the provider seam and record the generic ids.

    Called with the Payment row already locked by `_create_checkout_url_atomic`, so the
    lock ordering (platform settings -> makerspace settings -> Payment) is unchanged.
    """
    from apps.payments.providers import CheckoutRequest, get_provider

    provider = get_provider(payment.provider)
    result = provider.create_checkout(
        source,
        CheckoutRequest(
            # Integer minor units. A float here is a rounding bug that reconciles as a
            # real money difference.
            amount_minor=int(payment.amount * 100),
            currency=payment.currency,
            description=label,
            reference=str(payment.pk),
            success_url=f"{member_url}?checkout=success",
            cancel_url=f"{member_url}?checkout=cancelled",
            metadata={"payment_id": payment.pk, "makerspace_id": payment.makerspace_id},
            idempotency_key=_checkout_idempotency_key(payment),
        ),
    )
    payment.external_order_id = result.order_id
    payment.checkout_url = result.checkout_url
    payment.save(
        update_fields=["external_order_id", "checkout_url", "online_rail", "updated_at"]
    )
    return result.checkout_url


def _value(value, key):
    return value.get(key) if isinstance(value, dict) else getattr(value, key, None)


def _application_fee_amount(amount, basis_points):
    minor_units = (Decimal(amount) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(
        (minor_units * Decimal(basis_points) / Decimal(10000)).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
    )


def _checkout_idempotency_key(payment):
    generation = 0
    if payment.stripe_checkout_session_expired_at is not None:
        generation = int(
            payment.stripe_checkout_session_expired_at.timestamp() * 1_000_000
        )
    return f"payment-checkout-{payment.pk}-{generation}"


# Compatibility imports for established machine-service callers.
from apps.payments.reconciliation import mark_offline, waive  # noqa: E402
