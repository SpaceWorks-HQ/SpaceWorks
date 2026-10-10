"""Refund a paid-online charge through the provider seam.

Three steps, and the split is deliberate:

1. Under the Payment row lock: validate and write a PENDING `Refund` row. Pending rows
   count against the refundable balance, so two staff refunding at once cannot both pass.
2. Outside any row lock: call the provider. A webhook for the same payment must not queue
   behind vendor I/O, and a lock held across a network call is how deadlocks start.
3. Settle the row from the synchronous answer. Async providers leave it PENDING and the
   webhook (`services_refund_webhooks`) finishes the job idempotently.

The Payment row itself is never touched: it is terminal and the database forbids it.
"""

import logging
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone

from apps.audit import services as audit
from apps.payments.exceptions_refunds import RefundNotAllowed, RefundProviderFailure
from apps.payments.models import Payment, Refund
from apps.payments.money import to_minor_units
from apps.payments.providers import PaymentsUnavailable, RefundRequest, get_provider
from apps.payments.resolution import source_for_payment

logger = logging.getLogger(__name__)


def refund_payment(payment, *, amount, reason, actor):
    refund = _open_refund(payment, amount=amount, reason=reason, actor=actor)
    result, failed = _send_to_provider(refund)
    if failed:
        settle_refund(refund, external_refund_id=None, status=Refund.Status.FAILED, actor=actor)
        raise RefundProviderFailure(refund)
    settle_refund(refund, external_refund_id=result.refund_id, status=result.status, actor=actor)
    refund.refresh_from_db()
    return refund


def _open_refund(payment, *, amount, reason, actor):
    try:
        amount = Decimal(amount).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError, ValueError):
        raise RefundNotAllowed("Refund amount is invalid.", "refund_amount_invalid")
    if amount <= 0:
        raise RefundNotAllowed("Refund amount must be positive.", "refund_amount_invalid")
    with transaction.atomic():
        locked = Payment.objects.select_for_update().select_related("makerspace").get(pk=payment.pk)
        if locked.status != Payment.Status.PAID_ONLINE:
            # Offline charges are refunded through the core manual receipt service;
            # a provider cannot send back money it did not collect.
            raise RefundNotAllowed(
                "Only payments settled online can be refunded through the provider.",
                "refund_not_online",
            )
        if Refund.counted_total(locked) + amount > locked.amount:
            raise RefundNotAllowed(
                "Refund exceeds the refundable balance.", "refund_exceeds_balance"
            )
        return Refund.objects.create(
            payment=locked,
            amount=amount,
            currency=locked.currency,
            provider=locked.provider,
            reason=(reason or "")[:255],
            created_by=actor,
        )


def _send_to_provider(refund):
    payment = refund.payment
    try:
        source = source_for_payment(payment)
        if source is None:
            raise PaymentsUnavailable("The payment's provider credentials are no longer configured.")
        provider_payment_id = (
            payment.stripe_payment_intent_id
            if payment.provider == Payment.Provider.STRIPE
            else payment.external_payment_id
        )
        result = get_provider(payment.provider).create_refund(
            source,
            RefundRequest(
                payment_id=provider_payment_id or "",
                # Integer minor units; a float here reconciles as a real money difference.
                amount_minor=to_minor_units(refund.amount, refund.currency),
                currency=refund.currency,
                reference=str(refund.pk),
                idempotency_key=f"payment-refund-{refund.pk}",
                metadata={"refund_id": refund.pk, "payment_id": payment.pk},
            ),
        )
        return result, False
    except PaymentsUnavailable:
        logger.warning("payment_refund_provider_failed", extra={"refund_id": refund.pk})
        return None, True
    except Exception:
        logger.exception("payment_refund_provider_error", extra={"refund_id": refund.pk})
        return None, True


def settle_refund(refund, *, external_refund_id, status, actor):
    """Move a PENDING refund to its final state exactly once; later calls are no-ops.

    Shared by the synchronous path and the webhook path so both write the same audit
    entries with the same meta, whichever one gets there first.
    """
    with transaction.atomic():
        locked = Refund.objects.select_for_update().select_related("payment__makerspace").get(pk=refund.pk)
        fields = []
        if external_refund_id and not locked.external_refund_id:
            locked.external_refund_id = external_refund_id
            fields.append("external_refund_id")
        if locked.status != Refund.Status.PENDING:
            if fields:
                locked.save(update_fields=fields)
            return locked
        if status == Refund.Status.PENDING:
            if fields:
                locked.save(update_fields=fields)
            audit.record(
                actor, "payment.refund_requested",
                makerspace=locked.payment.makerspace, target=locked.payment,
                meta={"payment_id": locked.payment_id, "refund_id": locked.pk, "amount": str(locked.amount)},
            )
            return locked
        locked.status = status
        locked.settled_at = timezone.now()
        locked.save(update_fields=[*fields, "status", "settled_at"])
        action = "payment.refunded" if status == Refund.Status.SUCCEEDED else "payment.refund_failed"
        audit.record(
            actor, action,
            makerspace=locked.payment.makerspace, target=locked.payment,
            meta={"payment_id": locked.payment_id, "refund_id": locked.pk, "amount": str(locked.amount)},
        )
        return locked
