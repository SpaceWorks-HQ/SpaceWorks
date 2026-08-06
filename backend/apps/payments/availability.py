from apps.makerspaces.platform import feature_enabled
from apps.payments.resolution import resolve_payment_source


def online_payments_enabled(makerspace, domain):
    """Whether this makerspace may accept online payments for a domain.

    `payments.enabled` is an additive master switch (plan A6), not a replacement: the
    per-domain feature and configured credentials still both have to hold, so turning
    the master switch on can never make an unconfigured space start charging.
    """
    return (
        feature_enabled(makerspace, "payments.enabled")
        and feature_enabled(makerspace, f"payments.{domain}")
        and resolve_payment_source(makerspace) is not None
    )
