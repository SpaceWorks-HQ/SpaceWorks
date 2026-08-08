"""Platform SMS resolution.

Credentials live in the ``PlatformSmsSettings`` DB singleton rather than env vars,
matching ``PlatformEmailSettings``/``PlatformSocialAuthSettings``: an operator
configures SMS from ``/control/`` without a redeploy, and no new variable has to be
threaded through four compose services, both installers and ``.env.example``.

SMS here is **platform-scoped, for auth/OTP only**. Login resolves before a
makerspace is selected, so there is no tenant to bill or to read credentials from.
Per-makerspace SMS for reminders is a notification channel and is a separate
concern with separate credentials.
"""

import logging

from apps.integrations.sms.base import SmsDeliveryError, SmsProvider

logger = logging.getLogger(__name__)

__all__ = ["SmsDeliveryError", "SmsProvider", "get_sms_provider", "sms_configured", "send_sms"]


def _settings_row():
    from apps.integrations.models_sms import PlatformSmsSettings

    return PlatformSmsSettings.objects.filter(pk=1).first()


def get_sms_provider():
    """Return the configured provider, or None when SMS is not set up.

    Returning None (rather than raising) is what keeps the whole feature dormant:
    every caller treats None as "SMS is off" and the surfaces omit themselves.
    """
    row = _settings_row()
    if row is None or not row.is_enabled:
        return None
    if row.provider == "twilio":
        from apps.integrations.sms.twilio import TwilioSmsProvider

        provider = TwilioSmsProvider(row)
    else:
        # An unknown stored provider is a misconfiguration, not a crash: the choices
        # are validated at the form, so this can only be reached by a hand-edited row
        # or a downgrade. Fail closed and stay quiet in the payload.
        logger.warning("sms_provider_unknown", extra={"provider": row.provider})
        return None
    return provider if provider.is_configured() else None


def sms_configured() -> bool:
    return get_sms_provider() is not None


def send_sms(*, to: str, body: str) -> bool:
    """Best-effort send. False when SMS is off or the vendor rejected the message."""
    provider = get_sms_provider()
    if provider is None:
        return False
    try:
        return bool(provider.send(to=to, body=body))
    except Exception:
        # A provider that raises is a bug in that provider; never let it reach a
        # request flow. The caller's challenge row is already committed.
        logger.exception("sms_send_raised", extra={"provider": provider.key})
        return False
