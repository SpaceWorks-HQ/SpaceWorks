"""Verified failed attempts notify only the payer, after commit and once per event."""

import pytest
from django.db import transaction

from apps.audit.models import AuditLog
from apps.integrations.models import NotificationPreference
from apps.payments.models import Payment
from apps.payments.providers.base import WebhookEvent
from apps.payments.services_webhooks import apply_webhook_event, apply_razorpay_webhook_event
from tests.test_notification_families_f3 import family_world, capture_delivery

pytestmark = pytest.mark.django_db


def failed_event(space, payment, kind='payment_intent.payment_failed'):
    return apply_webhook_event(space, {'id': 'evt_failed', 'type': kind,
                                      'data': {'object': {'id': 'pi_failed' if kind.startswith('payment_intent') else 'cs_failed'}}})


@pytest.mark.parametrize('kind', ['payment_intent.payment_failed', 'checkout.session.async_payment_failed', 'razorpay'])
def test_failure_notifies_payer_after_commit_once_and_does_not_cancel_debt(monkeypatch, django_capture_on_commit_callbacks, kind):
    space, manager, member, payment = family_world('failed-' + kind.replace('.', '-'))
    NotificationPreference.objects.create(makerspace=space, feature='payments', channel='email', enabled=True)
    for channel in ('telegram', 'slack', 'webhook'):
        NotificationPreference.objects.create(makerspace=space, feature='payments', channel=channel, enabled=True)
    Payment.objects.filter(pk=payment.pk).update(provider='razorpay' if kind == 'razorpay' else 'stripe',
        stripe_payment_intent_id='pi_failed', stripe_checkout_session_id='cs_failed', external_order_id='order_failed')
    emails, channels = capture_delivery(monkeypatch)
    apply = (lambda: apply_razorpay_webhook_event(space, WebhookEvent(
        event_id='evt_failed', is_paid=False, is_failed=True, order_id='order_failed',
    ))) if kind == 'razorpay' else (lambda: failed_event(space, payment, kind))
    with django_capture_on_commit_callbacks(execute=True):
        assert apply() is not None
        assert apply() is None
        assert emails == channels == []
    assert len(emails) == 1 and emails[0]['to_email'] == member.email
    assert emails[0]['recipient_id'] == member.pk
    assert emails[0]['audience'] == 'requester' and channels == []
    payment.refresh_from_db()
    assert payment.status == Payment.Status.PENDING
    assert AuditLog.objects.filter(action='payment.failed', makerspace=space).count() == 1


def test_rollback_discards_failure_receipt_and_notification(monkeypatch, django_capture_on_commit_callbacks):
    space, _, _, payment = family_world('failed-rollback')
    Payment.objects.filter(pk=payment.pk).update(provider='stripe', stripe_payment_intent_id='pi_failed')
    emails, channels = capture_delivery(monkeypatch)
    with django_capture_on_commit_callbacks(execute=True):
        with pytest.raises(RuntimeError), transaction.atomic():
            failed_event(space, payment)
            raise RuntimeError('rollback')
    assert emails == channels == []
    assert not AuditLog.objects.filter(action='payment.failed').exists()


def test_verified_stripe_callback_cannot_match_another_provider_stale_handle(monkeypatch, django_capture_on_commit_callbacks):
    space, _, _, payment = family_world('failed-provider-boundary')
    Payment.objects.filter(pk=payment.pk).update(provider='razorpay', stripe_payment_intent_id='pi_failed')
    emails, channels = capture_delivery(monkeypatch)
    with django_capture_on_commit_callbacks(execute=True):
        assert failed_event(space, payment) is None
    assert emails == channels == [] and not AuditLog.objects.filter(action='payment.failed').exists()


def test_razorpay_signed_failure_is_normalized_and_forgery_is_refused():
    import json
    from apps.payments.providers import get_provider
    from apps.payments.providers.base import WebhookVerificationError
    from apps.payments.resolution import resolve_payment_source
    from tests.payments.test_razorpay_provider import configure_razorpay, sign
    space, _, _, _ = family_world('failed-signed-provider')
    configure_razorpay(space)
    source = resolve_payment_source(space)
    payload = json.dumps({'event': 'payment.failed', 'payload': {
        'payment': {'entity': {'id': 'pay_failed', 'order_id': 'order_failed'}},
    }}).encode()
    provider = get_provider('razorpay')
    event = provider.verify_webhook(source, payload=payload, headers={'X-Razorpay-Signature': sign(payload), 'X-Razorpay-Event-Id': 'evt_failure'})
    assert event.is_failed and not event.is_paid
    assert (event.payment_id, event.order_id, event.event_id) == ('pay_failed', 'order_failed', 'evt_failure')
    with pytest.raises(WebhookVerificationError):
        provider.verify_webhook(source, payload=payload, headers={'X-Razorpay-Signature': 'forged'})


def test_foreign_provider_handles_and_terminal_failures_do_not_notify(monkeypatch, django_capture_on_commit_callbacks):
    from tests.return_helpers import make_space, settlement_details
    from apps.payments.reconciliation import mark_offline
    space, manager, _, payment = family_world('failed-terminal')
    Payment.objects.filter(pk=payment.pk).update(provider='stripe', stripe_payment_intent_id='pi_failed')
    mark_offline(payment, manager, settlement_details())
    emails, channels = capture_delivery(monkeypatch)
    with django_capture_on_commit_callbacks(execute=True):
        assert failed_event(make_space('failed-foreign'), payment) is None
        assert failed_event(space, payment) is not None
    assert emails == channels == []
    assert not AuditLog.objects.filter(action='payment.failed').exists()
