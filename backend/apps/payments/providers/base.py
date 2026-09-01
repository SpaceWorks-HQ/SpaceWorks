"""The payment provider seam.

Two shipped implementations (Stripe, Razorpay) sit behind this protocol. The shape
mirrors ``apps/integrations/sms`` deliberately, which in turn was shaped like the
encryption key broker: a self-hoster whose country Stripe does not serve can add a
provider without touching a call site, and the booking/event/machine code never learns
which vendor is in play.

Three rules a provider must not break, each of which already governs the Stripe path:

* **Never block the domain action.** Machine ``complete()``/``collect()`` succeed even
  when checkout creation fails, so every method here raises ``PaymentsUnavailable``
  rather than an arbitrary vendor exception, and callers treat that as "no checkout
  yet", never as "the job did not finish".
* **Verify, then settle.** ``verify_webhook`` is given the raw request body and must do
  its own signature check. It must never trust a parsed body, because parsing is what
  loses the exact bytes the signature covers.
* **Amounts are integer minor units.** Both vendors take paise/cents as an int; a float
  anywhere in this path is a rounding bug that reconciles as a real money difference.
"""

from dataclasses import dataclass
from typing import Protocol

STRIPE = "stripe"
RAZORPAY = "razorpay"


class PaymentsUnavailable(Exception):
    """The provider cannot be reached or is not configured. Never fatal to a domain action."""


class WebhookVerificationError(Exception):
    """The request did not carry a signature this provider accepts.

    Deliberately distinct from ``PaymentsUnavailable``: an unverifiable webhook is a
    rejected request, not a degraded integration, and must never be settled.
    """


@dataclass(frozen=True)
class CheckoutRequest:
    """Everything a provider needs to raise a hosted payment page."""

    amount_minor: int
    currency: str
    description: str
    reference: str
    success_url: str
    cancel_url: str
    #: Echoed back on the webhook so a settlement can find its Payment row without
    #: trusting anything the payer could have edited.
    metadata: dict
    idempotency_key: str
    #: Stripe Connect only. Razorpay has no equivalent in this design -- see
    #: `razorpay.RazorpayProvider` for why it is self-host / own-account only.
    application_fee_minor: int = 0


@dataclass(frozen=True)
class CheckoutResult:
    """What the provider gave back. ``order_id`` is the row's idempotency anchor."""

    order_id: str
    checkout_url: str
    #: Present only when the provider settles synchronously at creation, which neither
    #: shipped provider does. Kept so a future provider need not widen the dataclass.
    payment_id: str = ""


@dataclass(frozen=True)
class WebhookEvent:
    """A verified, provider-agnostic settlement notification."""

    event_id: str
    #: True only for an event that means "the money is captured". Anything else is
    #: recorded for idempotency and otherwise ignored -- a provider must never report a
    #: pending or authorised-but-uncaptured payment as paid.
    is_paid: bool
    order_id: str = ""
    payment_id: str = ""
    #: The `metadata`/`notes` echoed back from CheckoutRequest.
    metadata: dict | None = None


class PaymentProvider(Protocol):
    #: Stable key stored on `Payment.provider` and `MakerspacePaymentSettings.provider`.
    key: str

    def create_checkout(self, source, request: CheckoutRequest) -> CheckoutResult:
        """Raise a hosted payment page. Raises PaymentsUnavailable on any failure."""
        ...

    def expire_checkout(self, source, order_id: str) -> None:
        """Best-effort cancellation of a live page. Must not raise on a missing order.

        Called when staff reconcile a payment offline or waive it, so a member cannot
        pay a charge that has already been settled another way. Best-effort because the
        reconciliation itself must succeed regardless.
        """
        ...

    def verify_webhook(self, source, *, payload: bytes, headers) -> WebhookEvent:
        """Verify the signature over the RAW body and return the event.

        Raises WebhookVerificationError if the signature does not match. Never returns
        an unverified event -- settling one would let anyone who can reach the endpoint
        mark any charge paid.
        """
        ...
