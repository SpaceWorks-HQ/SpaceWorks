"""Hosted provider requests and immutable currency/idempotency calculations."""

from decimal import Decimal, ROUND_HALF_UP

from apps.payments.money import to_minor_units


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
            amount_minor=to_minor_units(payment.amount, payment.currency),
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
    # A fresh page is live again, exactly as the Stripe branch resets it.
    payment.stripe_checkout_session_expired_at = None
    payment.save(
        update_fields=[
            "external_order_id", "checkout_url", "stripe_checkout_session_expired_at",
            "online_rail", "updated_at",
        ]
    )
    return result.checkout_url


def _value(value, key):
    return value.get(key) if isinstance(value, dict) else getattr(value, key, None)


def _application_fee_amount(amount, basis_points, currency):
    minor_units = Decimal(to_minor_units(amount, currency))
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
