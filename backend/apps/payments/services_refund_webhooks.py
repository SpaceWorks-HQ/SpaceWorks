"""Settle PENDING refunds from provider webhooks, idempotently.

Split from `services_webhooks` because that module sits at the file ceiling; the
idempotency helpers it shares with this one live here and are re-exported there.
Only refunds this deployment raised are settled: a refund made in a vendor dashboard
has no `Refund` row and no staff actor, so it is logged and left for reconciliation
to notice through the provider, never invented locally.
"""

import logging

from django.db import IntegrityError, transaction

from apps.payments.models import Payment, ProcessedStripeEvent, Refund
from apps.payments.services_refunds import settle_refund

logger = logging.getLogger(__name__)

STRIPE_REFUND_EVENT_TYPES = frozenset(
    {"charge.refunded", "charge.refund.updated", "refund.created", "refund.updated", "refund.failed"}
)
_STRIPE_STATUSES = {
    "succeeded": Refund.Status.SUCCEEDED,
    "failed": Refund.Status.FAILED,
    "canceled": Refund.Status.FAILED,
}


def _value(value, key):
    return value.get(key) if isinstance(value, dict) else getattr(value, key, None)


def _record_once(makerspace, event_id, provider=Payment.Provider.STRIPE):
    """Claim an event id, scoped by provider.

    Two vendors can mint the same event id; without the provider in the key the second
    one would be swallowed as a duplicate and a real charge would never settle.
    """
    try:
        ProcessedStripeEvent.objects.create(
            makerspace=makerspace, provider=provider, stripe_event_id=event_id
        )
    except IntegrityError:
        return False
    return True


def apply_stripe_refund_event(makerspace, event, *, provider, connected_account_id=None):
    event_id, event_type = _value(event, "id"), _value(event, "type")
    obj = _value(_value(event, "data") or {}, "object") or {}
    intent_id = _value(obj, "payment_intent")
    entries = _stripe_refund_entries(event_type, obj)
    if not event_id or not intent_id or not entries:
        return None
    with transaction.atomic():
        payments = Payment.objects.select_for_update().filter(
            makerspace=makerspace,
            provider=Payment.Provider.STRIPE,
            stripe_provider=provider,
            stripe_payment_intent_id=intent_id,
        )
        if connected_account_id is not None:
            payments = payments.filter(stripe_connected_account_id=connected_account_id)
        payment = payments.first()
        if payment is None or not _record_once(makerspace, event_id):
            return None
        return _settle_entries(payment, entries)


def apply_razorpay_refund_event(makerspace, event):
    """`event` is a providers.base.WebhookEvent carrying a refund id."""
    if not event.event_id or not event.refund_id or not event.payment_id:
        return None
    with transaction.atomic():
        payment = (
            Payment.objects.select_for_update()
            .filter(
                makerspace=makerspace,
                provider=Payment.Provider.RAZORPAY,
                external_payment_id=event.payment_id,
            )
            .first()
        )
        if payment is None or not _record_once(
            makerspace, event.event_id, Payment.Provider.RAZORPAY
        ):
            return None
        status = {
            "succeeded": Refund.Status.SUCCEEDED,
            "failed": Refund.Status.FAILED,
        }.get(event.refund_status, Refund.Status.PENDING)
        return _settle_entries(
            payment, [(event.refund_id, status, event.refund_amount_minor)]
        )


def _stripe_refund_entries(event_type, obj):
    """(external id, normalised status, amount in minor units) for each refund in the event."""
    if event_type == "charge.refunded":
        refunds = _value(_value(obj, "refunds") or {}, "data") or []
    elif event_type in STRIPE_REFUND_EVENT_TYPES:
        refunds = [obj]
    else:
        return []
    entries = []
    for refund in refunds:
        refund_id = _value(refund, "id")
        if not refund_id:
            continue
        status = _STRIPE_STATUSES.get(_value(refund, "status") or "", Refund.Status.PENDING)
        entries.append((refund_id, status, int(_value(refund, "amount") or 0)))
    return entries


def _settle_entries(payment, entries):
    settled = []
    for external_id, status, amount_minor in entries:
        row = _match_refund(payment, external_id, amount_minor)
        if row is None:
            logger.warning(
                "payment_refund_unmatched",
                extra={"payment_id": payment.pk, "provider": payment.provider},
            )
            continue
        settled.append(
            settle_refund(row, external_refund_id=external_id, status=status, actor=None)
        )
    return settled or None


def _match_refund(payment, external_id, amount_minor):
    """Our row for the provider's refund: by bound id first, else the oldest unbound
    PENDING refund of the same amount, which the settlement then binds."""
    rows = Refund.objects.select_for_update().filter(payment=payment, provider=payment.provider)
    bound = rows.filter(external_refund_id=external_id).first()
    if bound is not None:
        return bound
    unbound = rows.filter(external_refund_id__isnull=True, status=Refund.Status.PENDING)
    if amount_minor:
        unbound = [row for row in unbound.order_by("created_at", "pk") if int(row.amount * 100) == amount_minor]
        return unbound[0] if unbound else None
    return unbound.order_by("created_at", "pk").first()
