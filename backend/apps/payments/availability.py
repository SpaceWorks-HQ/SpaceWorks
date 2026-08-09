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
