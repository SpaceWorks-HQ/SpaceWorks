from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from apps.audit import services as audit
from apps.payments.models import (
    MakerspacePaymentSettings,
    Payment,
    ProcessedStripeEvent,
)
from apps.makerspaces.servability import is_servable


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
            payment.stripe_checkout_session_expired_at = timezone.now()
            payment.stripe_checkout_session_id = None
            payment.stripe_checkout_url = ""
            payment.save(
                update_fields=[
                    "stripe_checkout_session_expired_at",
                    "stripe_checkout_session_id",
                    "stripe_checkout_url",
                    "updated_at",
                ]
            )
            audit.record(
                None,
                "payment.checkout_expired",
                makerspace=makerspace,
                target=payment,
                meta={"stripe_event_id": event_id},
            )
            return payment
        if payment.status != Payment.Status.PENDING:
            audit.record(
                None,
                "payment.paid_after_terminal",
                makerspace=makerspace,
                target=payment,
                meta={"stripe_event_id": event_id, "prior_status": payment.status},
            )
            return payment
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
        return payment


def apply_connect_webhook_event(event):
    event_id = _value(event, "id")
    event_type = _value(event, "type")
    data = _value(event, "data") or {}
    obj = _value(data, "object") or {}
    account_id = _value(event, "account") or _value(obj, "id")
    event_created = _value(event, "created")
    if not event_id or not account_id:
        return None
    if event_type in {"account.updated", "account.application.deauthorized"}:
        return _apply_account_event(
            event_id, event_type, account_id, event_created=event_created
        )

    session_id = (
        _value(obj, "id") if str(event_type).startswith("checkout.session.") else None
    )
    intent_id = _value(obj, "payment_intent") or (
        _value(obj, "id") if event_type == "payment_intent.succeeded" else None
    )
    identifiers = Q()
    if session_id:
        identifiers |= Q(stripe_checkout_session_id=session_id)
    if intent_id:
        identifiers |= Q(stripe_payment_intent_id=intent_id)
    if not identifiers:
        return None
    payment = (
        Payment.objects.filter(
            stripe_provider=Payment.StripeProvider.CONNECT,
            stripe_connected_account_id=account_id,
        )
        .filter(identifiers)
        .select_related("makerspace")
        .first()
    )
    if payment is None:
        return None
    return apply_webhook_event(
        payment.makerspace,
        event,
        provider=Payment.StripeProvider.CONNECT,
        connected_account_id=account_id,
    )


def _apply_account_event(event_id, event_type, account_id, *, event_created):
    from apps.payments.connect import refresh_connected_account, restrict_account_status
    from apps.payments.stripe_client import PaymentsUnavailable

    with transaction.atomic():
        merchant = (
            MakerspacePaymentSettings.objects.select_for_update()
            .select_related("makerspace")
            .filter(connect_account_id=account_id)
            .first()
        )
        if merchant is None:
            return None
        if not is_servable(merchant.makerspace, allow_archived=True) or not _record_once(merchant.makerspace, event_id):
            return None
        if event_type == "account.application.deauthorized" and _event_is_stale(
            event_created, merchant.connect_account_assigned_at
        ):
            action = "payments.connect_deauthorization_ignored"
        elif event_type == "account.application.deauthorized":
            merchant.connect_status = MakerspacePaymentSettings.ConnectStatus.DISCONNECTED
            merchant.connect_charges_enabled = False
            merchant.connect_payouts_enabled = False
            merchant.connect_status_updated_at = timezone.now()
            merchant.save(
                update_fields=[
                    "connect_status",
                    "connect_charges_enabled",
                    "connect_payouts_enabled",
                    "connect_status_updated_at",
                ]
            )
            action = "payments.connect_deauthorized"
        elif (
            merchant.connect_status
            == MakerspacePaymentSettings.ConnectStatus.DISCONNECTED
        ):
            # Deauthorization is terminal locally. A delayed account.updated event
            # cannot reconnect the account, even if its payload predates deauth.
            action = "payments.connect_status_update_ignored"
        else:
            try:
                refresh_connected_account(merchant)
            except PaymentsUnavailable:
                restrict_account_status(merchant)
            action = "payments.connect_status_updated"
        audit.record(
            None,
            action,
            makerspace=merchant.makerspace,
            target=merchant,
            meta={"stripe_event_id": event_id},
        )
        return merchant


def _event_is_stale(event_created, account_assigned_at):
    if isinstance(event_created, bool) or not isinstance(event_created, (int, float)):
        return True
    if account_assigned_at is None:
        return False
    # Stripe event.created has whole-second precision. Treat events in the
    # assignment second as current so a later microsecond status refresh cannot
    # hide a legitimate deauthorization.
    return event_created < int(account_assigned_at.timestamp())


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


def apply_razorpay_webhook_event(makerspace, event):
    """Settle a VERIFIED Razorpay event. `event` is a providers.base.WebhookEvent.

    Same discipline as the Stripe path, and for the same reasons:

    * The row is found by the ids the provider echoed back, never by anything the payer
      supplied, and is locked before it is read.
    * Settlement happens **regardless of the live capability toggle**. A real charge must
      never be stranded because someone unticked a feature between checkout and callback.
    * A paid event for an already-terminal row is audited as `payment.paid_after_terminal`
      rather than dropped or re-applied, so a double charge is visible instead of silent.
    """
    if not is_servable(makerspace, allow_archived=True) or not event.event_id or not event.is_paid:
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
            audit.record(
                None,
                "payment.paid_after_terminal",
                makerspace=makerspace,
                target=payment,
                meta={"provider": "razorpay", "event_id": event.event_id, "prior_status": payment.status},
            )
            return payment
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
        return payment


def _value(value, key):
    return value.get(key) if isinstance(value, dict) else getattr(value, key, None)
