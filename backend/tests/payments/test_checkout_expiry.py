"""An expired hosted checkout must never be handed back to the member.

Before the fix, `checkout.session.expired` cleared only the Stripe-shaped columns, while
`create_checkout_url` returned the generic `checkout_url` first -- so after one expiry the
member was given the dead link on every retry and could never pay online again. The old
expiry test masked it by seeding only the Stripe columns with `.update()`.
"""

from decimal import Decimal

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.makerspaces.models import MakerspaceMembership
from apps.payments.models import Payment
from apps.payments.providers.razorpay import RazorpayProvider
from apps.payments.services import apply_webhook_event, create_checkout_url
from tests.payments.test_models import configured_settings
from tests.payments.test_razorpay_provider import configure_razorpay
from tests.return_helpers import enable_online_rail, make_member, make_space

pytestmark = pytest.mark.django_db


def _space_with_debt(slug, monkeypatch, *, razorpay=False):
    space = make_space(slug)
    enable_online_rail(space, "membership")
    configure_razorpay(space) if razorpay else configured_settings(space)
    member = make_member(f"{slug}-member", space)
    membership = MakerspaceMembership.objects.get(makerspace=space, user=member)
    payment = Payment.objects.create(
        makerspace=space,
        subject_type=Payment.SubjectType.MAKERSPACE_MEMBERSHIP,
        subject_id=membership.pk,
        member=member,
        amount=Decimal("15.00"),
        currency="usd",
        created_by=member,
        provider=Payment.Provider.RAZORPAY if razorpay else Payment.Provider.STRIPE,
    )
    monkeypatch.setattr(
        "apps.payments.services_checkout.member_payment_return_url",
        lambda _space: "https://space.example/member",
    )
    return space, member, payment


def _sessions(monkeypatch):
    minted = []

    def create(_source, **params):
        session_id = f"cs_gen_{len(minted)}"
        minted.append(params["idempotency_key"])
        return {"id": session_id, "url": f"https://checkout.stripe.test/{session_id}"}

    monkeypatch.setattr("apps.payments.services_checkout.stripe_client.create_checkout_session", create)
    return minted


def _expire(space, session_id, event_id="evt_expired"):
    event = {"id": event_id, "type": "checkout.session.expired", "data": {"object": {"id": session_id}}}
    return apply_webhook_event(space, event, provider=Payment.StripeProvider.RAW)


def _member_client(member):
    client = APIClient()
    client.force_authenticate(member)
    return client


def test_after_an_expiry_the_member_is_given_a_new_link_not_the_dead_one(monkeypatch):
    space, member, payment = _space_with_debt("expiry-regenerate", monkeypatch)
    minted = _sessions(monkeypatch)
    first = create_checkout_url(payment.pk)
    payment.refresh_from_db()
    assert payment.checkout_url == first == payment.stripe_checkout_url

    _expire(space, payment.stripe_checkout_session_id)

    payment.refresh_from_db()
    assert payment.stripe_checkout_session_expired_at is not None
    assert (payment.checkout_url, payment.stripe_checkout_url) == ("", "")
    assert (payment.external_order_id, payment.stripe_checkout_session_id) == (None, None)
    history = _member_client(member).get(f"/api/v1/member/makerspaces/{space.pk}/payments")
    assert history.data[0]["checkout_url"] == ""

    response = _member_client(member).post(
        f"/api/v1/member/makerspaces/{space.pk}/payments/{payment.pk}/checkout"
    )

    assert response.status_code == 200, response.data
    assert response.data["checkout_url"] != first
    assert len(minted) == 2 and minted[0] != minted[1]
    payment.refresh_from_db()
    assert payment.stripe_checkout_session_expired_at is None
    assert payment.checkout_url == response.data["checkout_url"]


def test_a_legacy_row_holding_only_the_generic_dead_link_is_regenerated(monkeypatch):
    """Rows expired before the fix kept `checkout_url`; the expiry stamp alone must win."""
    space, member, payment = _space_with_debt("expiry-legacy", monkeypatch)
    minted = _sessions(monkeypatch)
    Payment.objects.filter(pk=payment.pk).update(
        online_rail=Payment.OnlineRail.CHECKOUT,
        external_order_id="cs_dead",
        checkout_url="https://checkout.stripe.test/cs_dead",
        stripe_checkout_session_expired_at=timezone.now(),
    )

    response = _member_client(member).post(
        f"/api/v1/member/makerspaces/{space.pk}/payments/{payment.pk}/checkout"
    )

    assert response.status_code == 200
    assert response.data["checkout_url"] != "https://checkout.stripe.test/cs_dead"
    assert len(minted) == 1


def test_a_late_expiry_never_reopens_or_unsettles_a_paid_charge(monkeypatch):
    space, _member, payment = _space_with_debt("expiry-out-of-order", monkeypatch)
    _sessions(monkeypatch)
    create_checkout_url(payment.pk)
    payment.refresh_from_db()
    session_id = payment.stripe_checkout_session_id
    apply_webhook_event(
        space,
        {
            "id": "evt_paid",
            "type": "checkout.session.completed",
            "data": {"object": {"id": session_id, "payment_status": "paid", "payment_intent": "pi_paid"}},
        },
        provider=Payment.StripeProvider.RAW,
    )

    _expire(space, session_id, event_id="evt_late_expiry")

    payment.refresh_from_db()
    assert payment.status == Payment.Status.PAID_ONLINE
    # The refund anchor survives: a refund is sent against the intent, not the page.
    assert payment.stripe_payment_intent_id == "pi_paid"


def test_the_member_list_shows_a_live_razorpay_link(monkeypatch):
    space, member, payment = _space_with_debt("expiry-razorpay-link", monkeypatch, razorpay=True)
    monkeypatch.setattr(
        RazorpayProvider,
        "_request",
        lambda *_args, **_kwargs: {"id": "plink_live", "short_url": "https://rzp.io/i/live"},
    )
    create_checkout_url(payment.pk)

    response = _member_client(member).get(f"/api/v1/member/makerspaces/{space.pk}/payments")

    assert response.status_code == 200
    assert response.data[0]["checkout_url"] == "https://rzp.io/i/live"
