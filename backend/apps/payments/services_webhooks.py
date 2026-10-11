from django.db import transaction
from django.db.models import Q

from apps.audit import services as audit
from apps.payments.checkout_expiry import forget_closed_checkout
from apps.payments.models import Payment
from apps.payments.services_refund_webhooks import (  # noqa: F401  (_record_once re-exported)
    STRIPE_REFUND_EVENT_TYPES,
    _record_once,
    _value,
    apply_razorpay_refund_event,
    apply_stripe_refund_event,
)
from apps.payments.terminal_settlement import (
    handle_razorpay_paid_after_terminal,
    handle_stripe_paid_after_terminal,
)
from apps.makerspaces.servability import is_servable
from apps.payments.notifications import notify_payment
from apps.payments.admission_settlement import resume_admission_after_settlement


def apply_webhook_event(
    makerspace,
    event,
    *,
    provider=Payment.StripeProvider.RAW,
    connected_account_id=None,
):
    event_id = _value(event, "id")
    if not event_id or not is_servable(makerspace, allow_archived=True):
        return None
    event_type, data = _value(event, "type"), _value(event, "data") or {}
    obj = _value(data, "object") or {}
    if event_type in STRIPE_REFUND_EVENT_TYPES:
        return apply_stripe_refund_event(
            makerspace, event, provider=provider, connected_account_id=connected_account_id
        )
    if event_type not in {
        "checkout.session.completed",
        "checkout.session.async_payment_succeeded",
        "checkout.session.expired",
        "payment_intent.succeeded",
    }:
        return None
    if event_type == "checkout.session.completed" and _value(
        obj, "payment_status"
    ) not in {"paid", None}:
        return None
    session_id = (
        _value(obj, "id")
        if event_type in {
            "checkout.session.completed",
            "checkout.session.async_payment_succeeded",
            "checkout.session.expired",
        }
        else None
    )
    intent_id = _value(obj, "payment_intent") or (
        _value(obj, "id") if event_type == "payment_intent.succeeded" else None
    )
    if not session_id and not intent_id:
        return None
    with transaction.atomic():
        identifiers = Q()
        if session_id:
            identifiers |= Q(stripe_checkout_session_id=session_id)
        if intent_id:
            identifiers |= Q(stripe_payment_intent_id=intent_id)
        payments = Payment.objects.select_for_update().filter(
            makerspace=makerspace, stripe_provider=provider
        )
        if connected_account_id is not None:
            payments = payments.filter(
                stripe_connected_account_id=connected_account_id
            )
        payment = payments.filter(identifiers).first()
        if payment is None:
            return None
        if not _record_once(makerspace, event_id):
            return None
        if event_type == "checkout.session.expired":
            payment.save(update_fields=[*forget_closed_checkout(payment), "updated_at"])
            audit.record(
                None,
                "payment.checkout_expired",
                makerspace=makerspace,
                target=payment,
                meta={"stripe_event_id": event_id},
            )
            return payment
        if payment.status != Payment.Status.PENDING:
            return handle_stripe_paid_after_terminal(
                payment,
                event_id=event_id,
                intent_id=intent_id,
            )
        payment.status = Payment.Status.PAID_ONLINE
        if intent_id:
            payment.stripe_payment_intent_id = intent_id
        payment.save(update_fields=["status", "stripe_payment_intent_id", "updated_at"])
        audit.record(
            None,
            "payment.paid_online",
            makerspace=makerspace,
            target=payment,
            meta={"stripe_event_id": event_id},
        )
        from apps.payments.documents import issue_receipt
        issue_receipt(payment)
        notify_payment(payment, "payment_received")
        resume_admission_after_settlement(payment)
        return payment


def apply_razorpay_webhook_event(makerspace, event):
    """Settle a VERIFIED Razorpay event. `event` is a providers.base.WebhookEvent.

    Same discipline as the Stripe path, and for the same reasons:

    * The row is found by the ids the provider echoed back, never by anything the payer
      supplied, and is locked before it is read.
    * Settlement happens **regardless of the live capability toggle**. A real charge must
      never be stranded because someone unticked a feature between checkout and callback.
    * A paid event after waiver corrects the ledger; one after offline settlement raises
      an explicit refund-required audit condition instead of silently double-settling.
    """
    if not is_servable(makerspace, allow_archived=True) or not event.event_id:
        return None
    if event.refund_id:
        return apply_razorpay_refund_event(makerspace, event)
    if not event.is_paid:
        # Non-payment events are not recorded: claiming their id would make a later
        # genuine settlement carrying the same delivery id read as a duplicate.
        return None
    with transaction.atomic():
        identifiers = Q()
        if event.order_id:
            identifiers |= Q(external_order_id=event.order_id)
        if event.payment_id:
            identifiers |= Q(external_payment_id=event.payment_id)
        if not identifiers:
            return None
        payment = (
            Payment.objects.select_for_update()
            .filter(makerspace=makerspace, provider=Payment.Provider.RAZORPAY)
            .filter(identifiers)
            .first()
        )
        if payment is None:
            return None
        if not _record_once(makerspace, event.event_id, Payment.Provider.RAZORPAY):
            return None
        if payment.status != Payment.Status.PENDING:
            return handle_razorpay_paid_after_terminal(
                payment,
                event_id=event.event_id,
            )
        payment.status = Payment.Status.PAID_ONLINE
        fields = ["status", "updated_at"]
        if event.payment_id and not payment.external_payment_id:
            payment.external_payment_id = event.payment_id
            fields.insert(1, "external_payment_id")
        payment.save(update_fields=fields)
        audit.record(
            None,
            "payment.paid_online",
            makerspace=makerspace,
            target=payment,
            meta={"provider": "razorpay", "event_id": event.event_id},
        )
        from apps.payments.documents import issue_receipt
        issue_receipt(payment)
        notify_payment(payment, "payment_received")
        resume_admission_after_settlement(payment)
        return payment


# Explicit compatibility exports; callers keep the existing webhook import paths.
from apps.payments.services_connect_webhooks import (  # noqa: E402,F401
    apply_connect_webhook_event, _apply_account_event, _event_is_stale,
)
