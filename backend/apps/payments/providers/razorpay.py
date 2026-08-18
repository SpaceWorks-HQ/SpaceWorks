"""Razorpay, via Payment Links.

Payment Links rather than Orders + Checkout.js: the rest of this codebase hands the
member a URL and lets the vendor host the page (that is what Stripe Checkout gives us),
and an Orders-based flow would need a Razorpay JS widget embedded in the member area --
a second, differently-shaped payment UI to maintain. ``short_url`` is the direct
analogue of ``session.url``.

**Self-host / own-account only, by owner decision.** Razorpay has no equivalent of
Stripe Connect in this design, so there is no way to route a platform fee or to charge
on behalf of a tenant from a platform account. Managed hosting therefore keeps Stripe
Connect as its only rail, and `resolve_payment_source` never returns a Razorpay source
for a Connect-backed makerspace. Razorpay Route would be its own piece of work.

stdlib ``urllib`` rather than the vendor SDK, matching ``integrations/sms/twilio.py``:
three endpoints and an HMAC do not justify a dependency, and it keeps the seam honest
about how little a provider actually has to do.
"""

import hashlib
import hmac
import json
import logging
import urllib.error
import urllib.request
from base64 import b64encode

from apps.payments.providers.base import (
    RAZORPAY,
    CheckoutRequest,
    CheckoutResult,
    PaymentsUnavailable,
    WebhookEvent,
    WebhookVerificationError,
)

logger = logging.getLogger(__name__)

API_ROOT = "https://api.razorpay.com/v1"
TIMEOUT_SECONDS = 15

# Only these mean "the money is captured". `payment.authorized` deliberately does NOT:
# an authorised-but-uncaptured payment is not settled, and treating it as paid would
# mark a charge complete for money that can still fail to arrive.
PAID_EVENTS = frozenset({"payment_link.paid", "order.paid", "payment.captured"})


class RazorpayProvider:
    key = RAZORPAY

    # ---- HTTP ------------------------------------------------------------------

    def _request(self, source, method, path, body=None):
        if not (source.secret_key and source.publishable_key):
            raise PaymentsUnavailable("Razorpay credentials are not configured.")
        # publishable_key carries the key_id, secret_key the key_secret. Reusing the
        # existing PaymentSource fields keeps one resolution path for both providers
        # rather than a parallel Razorpay-shaped source object.
        token = b64encode(
            f"{source.publishable_key}:{source.secret_key}".encode()
        ).decode()
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(
            f"{API_ROOT}{path}",
            data=data,
            method=method,
            headers={
                "Authorization": f"Basic {token}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
                return json.loads(response.read().decode() or "{}")
        except urllib.error.HTTPError as exc:
            # The body can echo back the description and notes, which carry a member's
            # name. Log the status only -- an integration log is not the place for it.
            logger.warning(
                "razorpay_http_error", extra={"status": exc.code, "path": path}
            )
            raise PaymentsUnavailable("Razorpay rejected the request.") from exc
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            logger.warning("razorpay_unreachable", extra={"path": path})
            raise PaymentsUnavailable("Razorpay could not be reached.") from exc

    # ---- Provider protocol -----------------------------------------------------

    def create_checkout(self, source, request: CheckoutRequest) -> CheckoutResult:
        payload = {
            "amount": request.amount_minor,
            # Razorpay wants the ISO code uppercase; the rest of this codebase stores
            # currency lowercase, so the conversion belongs here rather than leaking a
            # provider's spelling into the Payment row.
            "currency": request.currency.upper(),
            "description": request.description[:2048],
            "reference_id": request.reference,
            "callback_url": request.success_url,
            "callback_method": "get",
            # Razorpay calls it `notes`; it is the `metadata` echo the webhook needs to
            # find the Payment row without trusting anything the payer could edit.
            "notes": {key: str(value) for key, value in (request.metadata or {}).items()},
            # We already email members ourselves through the notification matrix, and a
            # second unmanaged channel would bypass every recipient rule and module gate.
            "notify": {"sms": False, "email": False},
            "reminder_enable": False,
        }
        result = self._request(source, "POST", "/payment_links", payload)
        order_id, checkout_url = result.get("id"), result.get("short_url")
        if not order_id or not checkout_url:
            raise PaymentsUnavailable("Razorpay did not return a payment link.")
        return CheckoutResult(order_id=order_id, checkout_url=checkout_url)

    def expire_checkout(self, source, order_id: str) -> None:
        if not order_id:
            return
        try:
            self._request(source, "POST", f"/payment_links/{order_id}/cancel")
        except PaymentsUnavailable:
            # Best effort by contract: the reconciliation that called this must still
            # succeed. A link that outlives its payment is caught by the webhook, which
            # corrects a waiver or raises an explicit refund-required audit condition.
            logger.info("razorpay_link_cancel_failed", extra={"order_id": order_id})

    def verify_webhook(self, source, *, payload: bytes, headers) -> WebhookEvent:
        signature = headers.get("X-Razorpay-Signature") or headers.get(
            "HTTP_X_RAZORPAY_SIGNATURE", ""
        )
        secret = source.webhook_secret
        if not secret:
            raise WebhookVerificationError("No Razorpay webhook secret is configured.")
        if not signature:
            raise WebhookVerificationError("Missing Razorpay signature header.")
        expected = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
        # compare_digest, not ==: a short-circuiting comparison leaks the correct prefix
        # through timing, which is enough to forge a signature given enough attempts.
        if not hmac.compare_digest(expected, signature):
            raise WebhookVerificationError("Razorpay signature mismatch.")
        try:
            body = json.loads(payload.decode() or "{}")
        except ValueError as exc:
            raise WebhookVerificationError("Razorpay sent an unparseable body.") from exc

        event_type = body.get("event") or ""
        entities = body.get("payload") or {}
        link = (entities.get("payment_link") or {}).get("entity") or {}
        payment = (entities.get("payment") or {}).get("entity") or {}
        order = (entities.get("order") or {}).get("entity") or {}

        # Razorpay does not send a top-level event id, so the delivery id header is the
        # idempotency anchor. Falling back to the entity id keeps the record unique per
        # charge when a proxy strips the header, which is worse than the header but far
        # better than treating every delivery as new.
        event_id = (
            headers.get("X-Razorpay-Event-Id")
            or headers.get("HTTP_X_RAZORPAY_EVENT_ID")
            or f"{event_type}:{link.get('id') or payment.get('id') or order.get('id') or ''}"
        )
        return WebhookEvent(
            event_id=event_id,
            is_paid=event_type in PAID_EVENTS,
            order_id=link.get("id") or order.get("id") or payment.get("order_id") or "",
            payment_id=payment.get("id") or "",
            metadata=link.get("notes") or payment.get("notes") or order.get("notes") or {},
        )
