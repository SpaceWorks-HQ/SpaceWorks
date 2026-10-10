"""Connect account webhook handling, separated from charge settlement."""

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.audit import services as audit
from apps.payments.models import MakerspacePaymentSettings, Payment
from apps.payments.services_refund_webhooks import _record_once, _value
from apps.makerspaces.servability import is_servable


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
    from apps.payments.services_webhooks import apply_webhook_event
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
