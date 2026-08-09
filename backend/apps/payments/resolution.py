from dataclasses import dataclass

from apps.makerspaces.domain_verification import is_self_host
from apps.payments.models_settings import (
    MakerspacePaymentSettings,
    PlatformStripeConnectSettings,
)


@dataclass(frozen=True)
class PaymentSource:
    #: How STRIPE credentials were resolved: "raw" or "connect". Predates multi-vendor
    #: support and is meaningless for any other vendor -- see `vendor` for who holds
    #: the money. Not renamed because it is persisted on `Payment.stripe_provider`.
    provider: str
    secret_key: str
    webhook_secret: str
    #: For Razorpay this carries `key_id`, which is public exactly like a Stripe
    #: publishable key, so one field serves both and there is one resolution path.
    publishable_key: str = ""
    connected_account_id: str | None = None
    application_fee_bps: int = 0
    #: Which provider implementation should act on this source.
    vendor: str = "stripe"


def _razorpay_source(merchant) -> PaymentSource | None:
    """Razorpay is self-host / own-account only, by owner decision.

    There is no Razorpay equivalent of Stripe Connect here, so there is no platform
    account to charge on a tenant's behalf and no way to take an application fee.
    Managed hosting therefore keeps Connect as its only platform rail, and a Razorpay
    space always pays into its own merchant account -- which is why this returns None
    rather than falling through to any platform credential.
    """
    if not merchant.raw_credentials_configured:
        return None
    try:
        secret = merchant.get_razorpay_key_secret()
        webhook_secret = merchant.get_razorpay_webhook_secret()
    except Exception:
        return None
    if not (secret and webhook_secret and merchant.razorpay_key_id):
        return None
    return PaymentSource(
        "raw",
        secret,
        webhook_secret,
        publishable_key=merchant.razorpay_key_id,
        vendor="razorpay",
    )


def resolve_payment_source(makerspace) -> PaymentSource | None:
    merchant = MakerspacePaymentSettings.for_makerspace(makerspace)
    if merchant.provider == "razorpay":
        return _razorpay_source(merchant)
    if merchant.raw_credentials_configured:
        try:
            secret_key = merchant.get_stripe_secret_key()
            webhook_secret = merchant.get_stripe_webhook_secret()
        except Exception:
            return None
        if secret_key and webhook_secret:
            return PaymentSource(
                "raw",
                secret_key,
                webhook_secret,
                publishable_key=merchant.stripe_publishable_key,
            )

    if is_self_host():
        return None
    if not (
        merchant.connect_account_id
        and merchant.connect_status == MakerspacePaymentSettings.ConnectStatus.ACTIVE
        and merchant.connect_charges_enabled
    ):
        return None
    platform = PlatformStripeConnectSettings.load()
    if not platform.is_configured:
        return None
    try:
        secret_key = platform.get_stripe_secret_key()
        webhook_secret = platform.get_stripe_webhook_secret()
    except Exception:
        return None
    if not secret_key or not webhook_secret:
        return None
    return PaymentSource(
        "connect",
        secret_key,
        webhook_secret,
        publishable_key=platform.stripe_publishable_key,
        connected_account_id=merchant.connect_account_id,
        application_fee_bps=platform.application_fee_bps,
    )


def source_for_payment(payment) -> PaymentSource | None:
    """Credentials for an EXISTING row, resolved by what the row was created with.

    Deliberately keyed off the payment, never off the makerspace's current setting: a
    space that switches vendor must still be able to expire and settle the charges it
    raised under the old one. A row whose vendor no longer matches the merchant's
    credentials simply resolves to None and is reconciled offline.
    """
    if payment.provider == payment.Provider.RAZORPAY:
        return _razorpay_source(MakerspacePaymentSettings.for_makerspace(payment.makerspace))
    if payment.stripe_provider == payment.StripeProvider.RAW:
        merchant = MakerspacePaymentSettings.for_makerspace(payment.makerspace)
        if not merchant.raw_credentials_configured:
            return None
        try:
            return PaymentSource(
                "raw",
                merchant.get_stripe_secret_key(),
                merchant.get_stripe_webhook_secret(),
                publishable_key=merchant.stripe_publishable_key,
            )
        except Exception:
            return None
    if is_self_host() or not payment.stripe_connected_account_id:
        return None
    platform = PlatformStripeConnectSettings.load()
    if not platform.is_configured:
        return None
    try:
        return PaymentSource(
            "connect",
            platform.get_stripe_secret_key(),
            platform.get_stripe_webhook_secret(),
            publishable_key=platform.stripe_publishable_key,
            connected_account_id=payment.stripe_connected_account_id,
        )
    except Exception:
        return None
