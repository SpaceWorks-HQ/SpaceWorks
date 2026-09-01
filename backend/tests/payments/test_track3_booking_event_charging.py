from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.bookings import services_bookings
from apps.bookings.models import BookableSpace, Booking
from apps.events import services as event_services
from apps.events.models import Event, EventRegistration
from apps.events.service_payments import create_for_registered_registration
from apps.payments.models import MakerspacePaymentSettings, Payment
from tests.payments.test_models import configured_settings
from tests.return_helpers import make_member, make_space


pytestmark = pytest.mark.django_db


def member_with_phone(username, makerspace):
    member = make_member(username, makerspace)
    member.phone = "+919999999999"
    member.save(update_fields=["phone"])
    return member


def enable_payments(makerspace, domain, *, currency="usd"):
    makerspace.enabled_features = ["payments.enabled", f"payments.{domain}"]
    makerspace.save(update_fields=["enabled_features", "updated_at"])
    settings = configured_settings(makerspace)
    settings.default_currency = currency
    settings.save(update_fields=["default_currency"])


def bookable(makerspace, *, approval_mode="instant", amount="12.50"):
    return BookableSpace.objects.create(
        makerspace=makerspace,
        name=f"Room {BookableSpace.objects.count()}",
        approval_mode=approval_mode,
        payment_amount=amount,
        is_public=True,
    )


def create_booking(space, member, *, actor=None):
    starts_at = timezone.now() + timedelta(hours=2)
    return services_bookings.create_booking(
        space,
        starts_at=starts_at,
        ends_at=starts_at + timedelta(hours=1),
        member=member,
        actor=actor,
    )


def published_event(makerspace, actor, *, capacity=0, amount="8.00"):
    starts_at = timezone.now() + timedelta(days=1)
    return Event.objects.create(
        makerspace=makerspace,
        created_by=actor,
        title="Paid workshop",
        starts_at=starts_at,
        ends_at=starts_at + timedelta(hours=2),
        capacity=capacity,
        payment_amount=amount,
        is_public=True,
        status=Event.Status.PUBLISHED,
    )


def test_booking_instant_and_approval_charge_the_owned_member():
    makerspace = make_space("track3-booking-flows")
    enable_payments(makerspace, "bookings")
    manager = member_with_phone("track3-booking-manager", makerspace)
    member = member_with_phone("track3-booking-member", makerspace)

    instant = create_booking(bookable(makerspace), member, actor=None)
    instant_payment = Payment.objects.get(
        subject_type=Payment.SubjectType.BOOKING, subject_id=instant.pk
    )
    assert instant.status == Booking.Status.CONFIRMED
    assert (instant_payment.member, instant_payment.created_by) == (member, member)

    pending = create_booking(
        bookable(makerspace, approval_mode="approve"), member, actor=member
    )
    assert pending.status == Booking.Status.PENDING
    assert not Payment.objects.filter(subject_id=pending.pk).exists()
    services_bookings.approve_booking(pending, actor=manager)
    approved_payment = Payment.objects.get(
        subject_type=Payment.SubjectType.BOOKING, subject_id=pending.pk
    )
    assert (approved_payment.member, approved_payment.created_by) == (member, manager)


def test_booking_payment_and_checkout_failures_never_block_confirmation(
    monkeypatch, django_capture_on_commit_callbacks
):
    makerspace = make_space("track3-booking-nonblocking")
    enable_payments(makerspace, "bookings")
    member = member_with_phone("track3-booking-nonblocking-member", makerspace)

    monkeypatch.setattr(
        "apps.bookings.service_payments._get_or_create",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("database unavailable")),
    )
    first = create_booking(bookable(makerspace), member, actor=None)
    assert first.status == Booking.Status.CONFIRMED

    monkeypatch.undo()
    monkeypatch.setattr(
        "apps.bookings.service_payments.create_checkout",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("stripe unavailable")),
    )
    with django_capture_on_commit_callbacks(execute=True):
        second = create_booking(bookable(makerspace), member, actor=None)
    assert second.status == Booking.Status.CONFIRMED
    assert Payment.objects.filter(
        subject_type=Payment.SubjectType.BOOKING, subject_id=second.pk
    ).exists()


def test_event_registered_waitlisted_and_actorless_promotion_charge_once():
    makerspace = make_space("track3-event-promotion")
    enable_payments(makerspace, "events")
    manager = member_with_phone("track3-event-manager", makerspace)
    first_member = member_with_phone("track3-event-first", makerspace)
    waiter_member = member_with_phone("track3-event-waiter", makerspace)
    event = published_event(makerspace, manager, capacity=1)

    first = event_services.register(event, member=first_member, actor=None)
    waiter = event_services.register(event, member=waiter_member, actor=None)
    assert (first.status, waiter.status) == (
        EventRegistration.Status.REGISTERED,
        EventRegistration.Status.WAITLISTED,
    )
    assert Payment.objects.filter(
        subject_type=Payment.SubjectType.EVENT_REGISTRATION,
        subject_id=first.pk,
    ).count() == 1
    assert not Payment.objects.filter(subject_id=waiter.pk).exists()

    event_services.cancel_registration(first, actor=None)
    waiter.refresh_from_db()
    promoted = Payment.objects.get(
        subject_type=Payment.SubjectType.EVENT_REGISTRATION,
        subject_id=waiter.pk,
    )
    assert waiter.status == EventRegistration.Status.REGISTERED
    assert (promoted.member, promoted.created_by) == (waiter_member, waiter_member)
    create_for_registered_registration(waiter, None)
    assert Payment.objects.filter(
        subject_type=Payment.SubjectType.EVENT_REGISTRATION,
        subject_id=waiter.pk,
    ).count() == 1


def test_event_payment_failure_is_non_blocking(monkeypatch):
    makerspace = make_space("track3-event-nonblocking")
    enable_payments(makerspace, "events")
    manager = member_with_phone("track3-event-nonblocking-manager", makerspace)
    member = member_with_phone("track3-event-nonblocking-member", makerspace)
    event = published_event(makerspace, manager)
    monkeypatch.setattr(
        "apps.events.service_payments._get_or_create",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("payments down")),
    )

    registration = event_services.register(event, member=member, actor=None)

    assert registration.status == EventRegistration.Status.REGISTERED
    assert not Payment.objects.filter(subject_id=registration.pk).exists()


def test_booking_currency_is_snapshotted_and_cancellation_is_best_effort(monkeypatch):
    makerspace = make_space("track3-booking-currency")
    enable_payments(makerspace, "bookings", currency="eur")
    member = member_with_phone("track3-booking-currency-member", makerspace)
    booking = create_booking(bookable(makerspace), member, actor=None)
    payment = Payment.objects.get(subject_id=booking.pk)
    settings = MakerspacePaymentSettings.objects.get(makerspace=makerspace)
    settings.default_currency = "gbp"
    settings.save(update_fields=["default_currency"])
    Payment.objects.filter(pk=payment.pk).update(stripe_checkout_session_id="cs_cancel")
    monkeypatch.setattr(
        "apps.payments.reconciliation.stripe_client.expire_checkout_session",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("stripe down")),
    )

    services_bookings.cancel_booking(booking, actor=None)
    payment.refresh_from_db()

    assert payment.currency == "eur"
    assert payment.status == Payment.Status.CANCELED
    assert payment.stripe_checkout_session_expired_at is None
