"""Razorpay settlement, idempotency and immutable payment provenance."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.bookings.models import BookableSpace, Booking
from apps.payments.models import Payment, ProcessedStripeEvent
from tests.payments.test_razorpay_provider import configure_razorpay, make_space, paid_body, sign

pytestmark = pytest.mark.django_db


# --- settlement -------------------------------------------------------------


def make_payment(space, user, *, provider=Payment.Provider.RAZORPAY, order_id="plink_1"):
    starts_at = timezone.now() + timedelta(days=1)
    bookable = BookableSpace.objects.create(makerspace=space, name="Razorpay room", created_by=user)
    booking = Booking.objects.create(
        space=bookable, member=user, name=user.username,
        email=user.email or "payer@example.test", phone="1",
        starts_at=starts_at, ends_at=starts_at + timedelta(hours=1),
    )
    return Payment.objects.create(
        makerspace=space,
        subject_type=Payment.SubjectType.BOOKING,
        subject_id=booking.pk,
        amount=Decimal("10.00"),
        currency="inr",
        created_by=user,
        provider=provider,
        external_order_id=order_id,
    )


def test_a_verified_paid_event_settles_the_matching_payment(client, django_user_model):
    space = make_space()
    configure_razorpay(space)
    user = django_user_model.objects.create_user(username="staff", password="x")
    payment = make_payment(space, user)
    body = paid_body(payment_pk=payment.pk)

    response = client.post(
        reverse("razorpay-webhook", args=[space.public_code]),
        data=body,
        content_type="application/json",
        HTTP_X_RAZORPAY_SIGNATURE=sign(body),
        HTTP_X_RAZORPAY_EVENT_ID="evt_1",
    )

    payment.refresh_from_db()
    assert response.status_code == 200
    assert payment.status == Payment.Status.PAID_ONLINE
    assert payment.external_payment_id == "pay_1"


def test_replaying_the_same_event_settles_only_once(client, django_user_model):
    space = make_space()
    configure_razorpay(space)
    user = django_user_model.objects.create_user(username="staff", password="x")
    payment = make_payment(space, user)
    body = paid_body(payment_pk=payment.pk)
    post = lambda: client.post(  # noqa: E731
        reverse("razorpay-webhook", args=[space.public_code]),
        data=body,
        content_type="application/json",
        HTTP_X_RAZORPAY_SIGNATURE=sign(body),
        HTTP_X_RAZORPAY_EVENT_ID="evt_1",
    )

    post()
    post()

    assert ProcessedStripeEvent.objects.filter(makerspace=space).count() == 1


def test_two_providers_may_use_the_same_event_id(django_user_model):
    # Without the provider column in the idempotency key the second vendor's event
    # would be swallowed as a duplicate and a real charge would never settle.
    space = make_space()
    ProcessedStripeEvent.objects.create(makerspace=space, provider="stripe", stripe_event_id="evt_shared")

    ProcessedStripeEvent.objects.create(makerspace=space, provider="razorpay", stripe_event_id="evt_shared")

    assert ProcessedStripeEvent.objects.filter(stripe_event_id="evt_shared").count() == 2


def test_a_paid_event_for_a_terminal_payment_is_audited_not_reapplied(client, django_user_model):
    from apps.audit.models import AuditLog

    space = make_space()
    configure_razorpay(space)
    user = django_user_model.objects.create_user(username="staff", password="x")
    payment = make_payment(space, user)
    Payment.objects.filter(pk=payment.pk).update(status=Payment.Status.PAID_OFFLINE)
    body = paid_body(payment_pk=payment.pk)

    client.post(
        reverse("razorpay-webhook", args=[space.public_code]),
        data=body,
        content_type="application/json",
        HTTP_X_RAZORPAY_SIGNATURE=sign(body),
        HTTP_X_RAZORPAY_EVENT_ID="evt_late",
    )

    payment.refresh_from_db()
    assert payment.status == Payment.Status.PAID_OFFLINE
    assert AuditLog.objects.filter(action="payment.paid_after_terminal").exists()


# --- invariants that survive a second vendor --------------------------------


def test_the_provider_is_immutable_once_the_row_exists(django_user_model):
    space = make_space()
    user = django_user_model.objects.create_user(username="staff", password="x")
    payment = make_payment(space, user)

    payment.provider = Payment.Provider.STRIPE
    with pytest.raises(Exception, match="provenance is immutable"):
        payment.save()


def test_one_payment_per_subject_is_unchanged_by_the_provider_column(django_user_model):
    from django.core.exceptions import ValidationError

    space = make_space()
    user = django_user_model.objects.create_user(username="staff", password="x")
    payment = make_payment(space, user, order_id="plink_a")

    # Adding a provider column must not let a subject collect a second charge, one per
    # vendor. `Payment.save()` full_cleans, so the unique constraint surfaces as a
    # ValidationError before it ever reaches the database.
    with pytest.raises(ValidationError, match="already exists"):
        Payment.objects.create(
            makerspace=space,
            subject_type=Payment.SubjectType.BOOKING,
            subject_id=payment.subject_id,
            amount=Decimal("5.00"),
            currency="inr",
            created_by=user,
            provider=Payment.Provider.STRIPE,
        )


def test_two_vendors_may_mint_the_same_external_order_id(django_user_model):
    space = make_space()
    user = django_user_model.objects.create_user(username="staff", password="x")
    make_payment(space, user, order_id="shared_id")

    make_payment(space, user, provider=Payment.Provider.STRIPE, order_id="shared_id")

    assert Payment.objects.filter(external_order_id="shared_id").count() == 2


