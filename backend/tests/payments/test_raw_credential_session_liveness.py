from tests.return_helpers import settlement_details
import pytest
from rest_framework.test import APIClient

from apps.payments.models import Payment
from apps.payments.services import mark_offline, waive
from tests.payments.test_payment_settings_validation import pending_raw_settings


pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("reconcile", [mark_offline, waive])
def test_raw_rotation_blocks_terminal_session_when_remote_closure_is_unconfirmed(
    monkeypatch, reconcile
):
    makerspace, manager, payment_settings = pending_raw_settings(
        f"raw-terminal-unconfirmed-{reconcile.__name__}"
    )
    payment = Payment.objects.get(makerspace=makerspace)
    Payment.objects.filter(pk=payment.pk).update(
        stripe_checkout_url="https://checkout.stripe.test/raw-abandoned"
    )
    monkeypatch.setattr(
        "apps.payments.services_checkout.stripe_client.expire_checkout_session",
        lambda *_args: False,
    )
    # `mark_offline` requires the receipt; `waive` takes none, since no money moved.
    if reconcile is mark_offline:
        reconcile(payment, manager, settlement_details())
    else:
        reconcile(payment, manager)
    payment.refresh_from_db()
    assert payment.status in {Payment.Status.PAID_OFFLINE, Payment.Status.WAIVED}
    assert payment.stripe_checkout_session_expired_at is None
    monkeypatch.setattr(
        "apps.payments.stripe_client.checkout_session_is_closed",
        lambda *_args: False,
    )
    client = APIClient()
    client.force_authenticate(manager)

    response = client.patch(
        f"/api/v1/admin/makerspace/{makerspace.id}/payment-settings",
        {"stripe_secret_key": "sk_raw_rotated"},
        format="json",
    )

    assert response.status_code == 400
    payment_settings.refresh_from_db()
    assert payment_settings.get_stripe_secret_key() == "sk_raw"


def test_raw_rotation_persists_authoritatively_closed_terminal_session(monkeypatch):
    makerspace, manager, payment_settings = pending_raw_settings(
        "raw-terminal-confirmed-closed"
    )
    payment = Payment.objects.get(makerspace=makerspace)
    monkeypatch.setattr(
        "apps.payments.services_checkout.stripe_client.expire_checkout_session",
        lambda *_args: False,
    )
    mark_offline(payment, manager, settlement_details())
    monkeypatch.setattr(
        "apps.payments.stripe_client.checkout_session_is_closed",
        lambda *_args: True,
    )
    client = APIClient()
    client.force_authenticate(manager)

    response = client.patch(
        f"/api/v1/admin/makerspace/{makerspace.id}/payment-settings",
        {"stripe_secret_key": "sk_raw_rotated"},
        format="json",
    )

    assert response.status_code == 200
    payment.refresh_from_db()
    payment_settings.refresh_from_db()
    assert payment.stripe_checkout_session_expired_at is not None
    assert payment.stripe_checkout_session_id is None
    assert payment.stripe_checkout_url == ""
    assert payment_settings.get_stripe_secret_key() == "sk_raw_rotated"
