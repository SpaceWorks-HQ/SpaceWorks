"""The SMS provider seam.

One shipped implementation (Twilio) sits behind this protocol. The shape mirrors
``apps/encryption``'s key broker deliberately: a self-hoster outside Twilio's
footprint can add a provider without touching any call site, and the auth/OTP
code never learns which vendor is in play.

A provider returns True only when the vendor accepted the message for delivery.
It must never raise for a delivery failure -- callers treat SMS the same way the
codebase treats every other outbound integration (fail safe, never crash a
request flow), and an OTP that could not be sent must still leave a consumable
challenge row behind so the generic acknowledgement stays honest.
"""

from typing import Protocol


class SmsDeliveryError(Exception):
    """Raised only for a misconfigured provider, never for a rejected send."""


class SmsProvider(Protocol):
    #: Stable key stored in PlatformSmsSettings.provider.
    key: str

    def is_configured(self) -> bool:
        """True when this provider holds every credential it needs to send."""
        ...

    def send(self, *, to: str, body: str) -> bool:
        """Deliver `body` to the E.164 number `to`. False on a rejected send."""
        ...
