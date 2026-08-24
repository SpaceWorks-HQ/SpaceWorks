from decimal import Decimal

import pytest

from apps.payments.models import Payment
from apps.tenant_migration.tenant_dump_cross_tenant import PAYMENT_CLEARED_VALUES
from tests.return_helpers import authenticated_client, make_member, make_space


pytestmark = pytest.mark.django_db


TERMINAL_STATUSES = (
    Payment.Status.PAID_ONLINE,
    Payment.Status.PAID_OFFLINE,
    Payment.Status.WAIVED,
    Payment.Status.CANCELED,
)


def _restored_terminal_payment(space, actor, status):
    payment = Payment(
        makerspace=space,
        subject_type=Payment.SubjectType.BOOKING,
        subject_id=8000 + TERMINAL_STATUSES.index(status),
        subject_label="Imported historical booking",
        member=actor,
        amount=Decimal("42.75"),
        currency="inr",
        status=status,
        provider=Payment.Provider.RAZORPAY,
        via_makerspace=None,
        external_order_id=None,
        external_payment_id=None,
        checkout_url="",
        stripe_provider=Payment.StripeProvider.RAW,
        stripe_connected_account_id=None,
        stripe_application_fee_amount=0,
        online_rail=None,
        stripe_checkout_session_id=None,
        stripe_checkout_url="",
        stripe_checkout_session_expired_at=None,
        stripe_payment_intent_id=None,
        created_by=actor,
    )
    Payment.objects.bulk_create([payment])
    return Payment.objects.get(
        makerspace=space, subject_id=payment.subject_id
    )


@pytest.mark.parametrize("status", TERMINAL_STATUSES)
def test_each_restored_terminal_payment_is_readable_secret_free_and_provider_inert(
    status, monkeypatch
):
    space = make_space(f"d8-terminal-{status}")
    manager = make_member(f"d8-terminal-{status}-manager", space)
    payment = _restored_terminal_payment(space, manager, status)
    provider_calls = []

    def provider_called(*args, **kwargs):
        provider_calls.append((args, kwargs))
        raise AssertionError("a restored terminal payment reached a provider")

    monkeypatch.setattr(
        "apps.payments.reconciliation.source_for_payment", provider_called
    )
    monkeypatch.setattr(
        "apps.payments.reconciliation.stripe_client.expire_checkout_session",
        provider_called,
    )
    monkeypatch.setattr(
        "apps.payments.reconciliation.stripe_client.cancel_payment_intent",
        provider_called,
    )
    monkeypatch.setattr(
        "apps.payments.providers.get_provider", provider_called
    )
    client = authenticated_client(manager)
    base = f"/api/v1/admin/makerspace/{space.pk}/payments"

    listed = client.get(base)
    reconciled = client.post(f"{base}/{payment.pk}/mark-offline")

    assert listed.status_code == 200
    row = next(item for item in listed.data if item["id"] == payment.pk)
    assert row["status"] == status
    assert Decimal(row["amount"]) == Decimal("42.75")
    assert row["currency"] == "inr"
    assert reconciled.status_code == 409
    assert reconciled.data["code"] == "payment_terminal"
    payment.refresh_from_db()
    assert payment.status == status
    assert payment.provider == Payment.Provider.RAZORPAY
    for field_name, expected in PAYMENT_CLEARED_VALUES.items():
        assert getattr(payment, field_name) == expected
    assert provider_calls == []
