"""Provider registry.

Declared, not discovered. A provider is a money path: it must be added deliberately,
by someone who has read what it does, rather than by dropping a file into a directory.
"""

from apps.payments.providers.base import (  # noqa: F401  (re-exported for callers)
    RAZORPAY,
    STRIPE,
    CheckoutRequest,
    CheckoutResult,
    PaymentProvider,
    PaymentsUnavailable,
    WebhookEvent,
    WebhookVerificationError,
)
from apps.payments.providers.razorpay import RazorpayProvider
from apps.payments.providers.stripe import StripeProvider

PROVIDERS = {
    STRIPE: StripeProvider(),
    RAZORPAY: RazorpayProvider(),
}

PROVIDER_CHOICES = tuple((key, key.title()) for key in PROVIDERS)


def get_provider(key):
    """Return the provider for `key`.

    Unknown keys raise rather than defaulting to Stripe. A row whose provider we cannot
    identify must not be charged or settled through a guess -- that is how money ends up
    in the wrong merchant account.
    """
    provider = PROVIDERS.get(key)
    if provider is None:
        raise PaymentsUnavailable(f"Unknown payment provider {key!r}.")
    return provider
