from django.db import transaction

from apps.audit import services as audit
from apps.payments import stripe_client
from apps.payments.connect import refresh_connected_account
from apps.payments.models import (
    MakerspacePaymentSettings,
    Payment,
    PlatformStripeConnectSettings,
)
from apps.payments.resolution import source_for_payment
from apps.payments.services import PaymentRailConflict
from apps.payments.services_checkout import _claim_provider


def create_mobile_intent(payment_id, *, actor):
    snapshot = Payment.objects.only(
        'makerspace_id', 'stripe_provider', 'provider'
    ).get(pk=payment_id)
    with transaction.atomic():
        # An unclaimed row's rail is unknown until the source resolves and may turn out
        # to be Connect, so the platform lock is taken speculatively to preserve the
        # platform -> makerspace -> Payment order. Its absence only matters for a row
        # already stamped Connect; a self-hosted deployment has no platform row at all.
        unclaimed = snapshot.provider == Payment.Provider.UNCLAIMED
        if snapshot.stripe_provider == Payment.StripeProvider.CONNECT or unclaimed:
            platform = (
                PlatformStripeConnectSettings.objects.select_for_update()
                .filter(pk=1)
                .first()
            )
            if platform is None and not unclaimed:
                raise stripe_client.PaymentsUnavailable(
                    'Stripe Connect is not configured.'
                )
        merchant = (
            MakerspacePaymentSettings.objects.select_for_update()
            .filter(makerspace_id=snapshot.makerspace_id)
            .first()
        )
        payment = (
            Payment.objects.select_for_update()
            .select_related('makerspace')
            .get(pk=payment_id)
        )
        if payment.status != Payment.Status.PENDING:
            raise Payment.DoesNotExist
        if payment.online_rail == Payment.OnlineRail.CHECKOUT:
            raise PaymentRailConflict(
                'The payment already uses the Checkout payment rail.'
            )
        # Claim the rail before creating a provider object, exactly as hosted checkout
        # does. Without this a cash-raised charge could settle online while still stamped
        # `unclaimed`, which would misreport it and leave refunds with no vendor to
        # dispatch to.
        if payment.provider == Payment.Provider.UNCLAIMED:
            _claim_provider(payment)
        source = source_for_payment(payment)
        if source is None or not source.publishable_key:
            raise stripe_client.PaymentsUnavailable(
                'Mobile payments are not configured.'
            )
        _validate_connect_source(payment, merchant)

        if payment.stripe_payment_intent_id:
            intent = stripe_client.retrieve_payment_intent(
                source, payment.stripe_payment_intent_id
            )
        else:
            intent = stripe_client.create_payment_intent(
                source,
                idempotency_key=f'payment-mobile-intent-{payment.pk}',
                **_intent_params(payment),
            )
        intent_id = _value(intent, 'id')
        client_secret = _value(intent, 'client_secret')
        if not intent_id or not client_secret:
            raise stripe_client.PaymentsUnavailable(
                'Stripe did not return a usable payment intent.'
            )
        if (
            payment.stripe_payment_intent_id
            and payment.stripe_payment_intent_id != intent_id
        ):
            raise stripe_client.PaymentsUnavailable(
                'Stripe returned an unexpected payment intent.'
            )
        if payment.stripe_payment_intent_id is None:
            payment.online_rail = Payment.OnlineRail.NATIVE_PAYMENT_INTENT
            payment.stripe_payment_intent_id = intent_id
            payment.save(
                update_fields=[
                    'online_rail',
                    'stripe_payment_intent_id',
                    'updated_at',
                ]
            )
            audit.record(
                actor,
                'payment.mobile_intent_created',
                makerspace=payment.makerspace,
                target=payment,
                meta={'stripe_provider': payment.stripe_provider},
            )
        return {
            'payment_id': payment.pk,
            'client_secret': client_secret,
            'publishable_key': source.publishable_key,
        }


def _validate_connect_source(payment, merchant):
    if payment.stripe_provider != Payment.StripeProvider.CONNECT:
        return
    if (
        merchant is None
        or merchant.connect_account_id != payment.stripe_connected_account_id
    ):
        raise stripe_client.PaymentsUnavailable(
            'Stripe Connect account is unavailable.'
        )
    refreshed = refresh_connected_account(merchant)
    if not (
        refreshed.connect_status == MakerspacePaymentSettings.ConnectStatus.ACTIVE
        and refreshed.connect_charges_enabled
    ):
        raise stripe_client.PaymentsUnavailable(
            'Stripe Connect account cannot accept charges.'
        )


def _intent_params(payment):
    params = {
        'amount': int(payment.amount * 100),
        'currency': payment.currency,
        'automatic_payment_methods': {'enabled': True},
        'metadata': {
            'payment_id': str(payment.pk),
            'makerspace_id': str(payment.makerspace_id),
        },
    }
    if payment.stripe_application_fee_amount:
        params['application_fee_amount'] = payment.stripe_application_fee_amount
    return params


def _value(value, key):
    return value.get(key) if isinstance(value, dict) else getattr(value, key, None)
