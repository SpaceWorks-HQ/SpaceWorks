"""A verified failure is an attempt outcome, never a cancellation of the debt."""

from apps.audit import services as audit
from apps.payments.models import Payment
from apps.payments.notifications import notify_payment


def record_payment_failure(payment, *, event_id, provider):
    # Called under the payment lock after the provider event receipt was claimed.
    # A delayed failure must not tell a payer their already settled charge failed.
    if payment.status != Payment.Status.PENDING:
        return payment
    audit.record(None, "payment.failed", makerspace=payment.makerspace, target=payment,
                 meta={"provider": provider, "event_id": event_id})
    notify_payment(payment, "payment_failed", requester_only=True)
    return payment
