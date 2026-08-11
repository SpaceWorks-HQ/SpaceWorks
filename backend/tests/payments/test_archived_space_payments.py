import hashlib
import hmac
import json
import time
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.accounts.models import User
from apps.makerspaces.models import MakerspaceMembership
from apps.payments.models import MakerspacePaymentSettings, Payment
from tests.payments.test_models import configured_settings
from tests.return_helpers import (
    authenticated_client,
    make_member,
    make_space,
    make_user,
)


pytestmark = pytest.mark.django_db


def _archive(space):
    space.archived_at = timezone.now()
    space.save(update_fields=["archived_at", "updated_at"])


def _membership_payment(space, member, *, provider=Payment.Provider.STRIPE):
    membership = MakerspaceMembership.objects.get(makerspace=space, user=member)
    return Payment.objects.create(
        makerspace=space,
        subject_type=Payment.SubjectType.MAKERSPACE_MEMBERSHIP,
        subject_id=membership.pk,
        member=member,
        amount=Decimal("10.00"),
        currency="usd" if provider == Payment.Provider.STRIPE else "inr",
        created_by=member,
        provider=provider,
        subject_label="Membership dues",
    )


def _stripe_signature(body, secret="whsec_test_secret"):
    timestamp = int(time.time())
    signed = f"{timestamp}.".encode() + body
    digest = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={digest}"


def _configure_razorpay(space, secret="rzp_webhook_secret"):
    settings_row = MakerspacePaymentSettings(makerspace=space, provider="razorpay")
    settings_row.razorpay_key_id = "rzp_test_key"
    settings_row.set_razorpay_key_secret("rzp_test_secret")
    settings_row.set_razorpay_webhook_secret(secret)
    settings_row.save()
    return secret


def test_member_payment_history_survives_archival_without_leaking_other_rows():
    space = make_space("archived-payment-history")
    member = make_member("archived-payment-history-member", space)
    own_payment = _membership_payment(space, member)

    other_member = make_member("archived-payment-history-other", space)
    _membership_payment(space, other_member)

    unrelated_space = make_space("archived-payment-history-unrelated")
    unrelated_membership = MakerspaceMembership.objects.create(
        makerspace=unrelated_space,
        user=member,
        role=MakerspaceMembership.Role.SPACE_MANAGER,
    )
    Payment.objects.create(
        makerspace=unrelated_space,
        subject_type=Payment.SubjectType.MAKERSPACE_MEMBERSHIP,
        subject_id=unrelated_membership.pk,
        member=member,
        amount=Decimal("20.00"),
        currency="usd",
        created_by=member,
        subject_label="Other membership dues",
    )
    _archive(space)

    response = authenticated_client(member).get(
        f"/api/v1/member/makerspaces/{space.pk}/payments"
    )

    assert response.status_code == 200
    assert [row["id"] for row in response.data] == [own_payment.pk]


def test_web_checkout_tolerates_archival_for_an_active_member(monkeypatch):
    space = make_space("archived-payment-checkout")
    member = make_member("archived-payment-checkout-member", space)
    configured_settings(space)
    payment = _membership_payment(space, member)
    _archive(space)
    monkeypatch.setattr(
        "apps.payments.services.stripe_client.create_checkout_session",
        lambda *_args, **_kwargs: {
            "id": "cs_archived",
            "url": "https://checkout.stripe.test/cs_archived",
        },
    )

    response = authenticated_client(member).post(
        f"/api/v1/member/makerspaces/{space.pk}/payments/{payment.pk}/checkout"
    )

    assert response.status_code == 200
    assert response.data["checkout_url"] == "https://checkout.stripe.test/cs_archived"
    assert MakerspaceMembership.objects.get(makerspace=space, user=member).status == "active"


def test_raw_stripe_webhook_settles_after_archival():
    space = make_space("archived-stripe-webhook")
    member = make_member("archived-stripe-webhook-member", space)
    configured_settings(space)
    payment = _membership_payment(space, member)
    Payment.objects.filter(pk=payment.pk).update(
        stripe_checkout_session_id="cs_archived_webhook"
    )
    _archive(space)
    body = json.dumps(
        {
            "id": "evt_archived_stripe",
            # Stripe's SDK reads a top-level `object` before anything else
            # (`construct_event` -> `event.object`), so a payload without it raises
            # AttributeError instead of verifying.
            "object": "event",
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": "cs_archived_webhook",
                    "payment_status": "paid",
                    "payment_intent": "pi_archived_webhook",
                }
            },
        },
        separators=(",", ":"),
    ).encode()

    response = authenticated_client(member).generic(
        "POST",
        f"/api/v1/webhooks/stripe/{space.public_code}",
        body,
        content_type="application/json",
        HTTP_STRIPE_SIGNATURE=_stripe_signature(body),
    )

    payment.refresh_from_db()
    assert response.status_code == 200
    assert payment.status == Payment.Status.PAID_ONLINE


def test_razorpay_webhook_settles_after_archival():
    space = make_space("archived-razorpay-webhook")
    member = make_member("archived-razorpay-webhook-member", space)
    secret = _configure_razorpay(space)
    payment = _membership_payment(space, member, provider=Payment.Provider.RAZORPAY)
    Payment.objects.filter(pk=payment.pk).update(external_order_id="plink_archived")
    _archive(space)
    body = json.dumps(
        {
            "event": "payment_link.paid",
            "payload": {
                "payment_link": {
                    "entity": {
                        "id": "plink_archived",
                        "notes": {"payment_id": str(payment.pk)},
                    }
                },
                "payment": {"entity": {"id": "pay_archived"}},
            },
        },
        separators=(",", ":"),
    ).encode()
    signature = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

    response = authenticated_client(member).generic(
        "POST",
        f"/api/v1/webhooks/razorpay/{space.public_code}",
        body,
        content_type="application/json",
        HTTP_X_RAZORPAY_SIGNATURE=signature,
        HTTP_X_RAZORPAY_EVENT_ID="evt_archived_razorpay",
    )

    payment.refresh_from_db()
    assert response.status_code == 200
    assert payment.status == Payment.Status.PAID_ONLINE


def test_revoked_membership_cannot_read_archived_payment_history():
    space = make_space("archived-payment-revoked")
    member = make_member("archived-payment-revoked-member", space)
    membership = MakerspaceMembership.objects.get(makerspace=space, user=member)
    membership.status = "revoked"
    membership.save(update_fields=["status"])
    _archive(space)

    response = authenticated_client(member).get(
        f"/api/v1/member/makerspaces/{space.pk}/payments"
    )

    assert response.status_code == 403
    assert response.data == {"detail": "An active membership is required."}


@pytest.mark.parametrize(
    "access_status",
    [User.AccessStatus.RESTRICTED, User.AccessStatus.SUSPENDED],
)
def test_blocked_account_cannot_read_archived_payment_history(access_status):
    space = make_space(f"archived-payment-{access_status}")
    member = make_user(
        f"archived-payment-{access_status}-member",
        access_status=access_status,
    )
    MakerspaceMembership.objects.create(makerspace=space, user=member, status="active")
    _archive(space)

    response = authenticated_client(member).get(
        f"/api/v1/member/makerspaces/{space.pk}/payments"
    )

    assert response.status_code == 403
    assert response.data == {"detail": "An active membership is required."}
