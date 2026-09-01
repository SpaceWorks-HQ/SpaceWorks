"""Narrow exception for money received after a charge was waived."""

from django.db import connection
from django.utils import timezone

from apps.audit import services as audit
from apps.payments.models import Payment


def handle_stripe_paid_after_terminal(payment, *, event_id, intent_id=None):
    """Correct or flag a late Stripe payment after staff reconciliation."""
    prior_status = payment.status
    if prior_status == Payment.Status.WAIVED:
        promote_waived_to_paid_online(payment, intent_id=intent_id)

    audit.record(
        None,
        "payment.paid_after_terminal",
        makerspace=payment.makerspace,
        target=payment,
        meta={
            "stripe_event_id": event_id,
            "prior_status": prior_status,
            "resolved_status": payment.status,
        },
    )
    if prior_status == Payment.Status.PAID_OFFLINE:
        audit.record(
            None,
            "payment.double_paid_refund_required",
            makerspace=payment.makerspace,
            target=payment,
            meta={"stripe_event_id": event_id, "prior_status": prior_status},
        )
    return payment


def handle_razorpay_paid_after_terminal(payment, *, event_id):
    """Correct or flag a late Razorpay payment after staff reconciliation."""
    prior_status = payment.status
    if prior_status == Payment.Status.WAIVED:
        promote_waived_to_paid_online(payment)

    audit.record(
        None,
        "payment.paid_after_terminal",
        makerspace=payment.makerspace,
        target=payment,
        meta={
            "provider": "razorpay",
            "event_id": event_id,
            "prior_status": prior_status,
            "resolved_status": payment.status,
        },
    )
    if prior_status == Payment.Status.PAID_OFFLINE:
        audit.record(
            None,
            "payment.double_paid_refund_required",
            makerspace=payment.makerspace,
            target=payment,
            meta={
                "provider": "razorpay",
                "event_id": event_id,
                "prior_status": prior_status,
            },
        )
    return payment


def promote_waived_to_paid_online(payment, *, intent_id=None):
    """Correct a locked waived row after the provider confirms real payment.

    The database GUC is transaction-scoped, and the trigger accepts only the exact
    ``waived`` to ``paid_online`` transition with an unchanged amount. Callers must hold
    the payment row lock inside an atomic block.
    """
    with connection.cursor() as cursor:
        cursor.execute("SET LOCAL app.allow_waived_online_settlement = 'on'")

    updates = {
        "status": Payment.Status.PAID_ONLINE,
        "updated_at": timezone.now(),
    }
    if intent_id:
        updates["stripe_payment_intent_id"] = intent_id
    changed = Payment.objects.filter(
        pk=payment.pk, status=Payment.Status.WAIVED
    ).update(**updates)
    if changed != 1:
        raise RuntimeError("The waived payment could not be settled.")
    payment.status = Payment.Status.PAID_ONLINE
    payment.updated_at = updates["updated_at"]
    if intent_id:
        payment.stripe_payment_intent_id = intent_id
    return payment
