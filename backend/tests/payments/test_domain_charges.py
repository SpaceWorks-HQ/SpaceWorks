from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from django.core.exceptions import ValidationError
from django.db import close_old_connections
from django.utils import timezone

from apps.accounts.models import User
from apps.bookings import service_payments as booking_payments
from apps.bookings import services_bookings
from apps.bookings.models import BookableSpace, Booking
from apps.events import service_payments as event_payments
from apps.events import services as event_services
from apps.events.models import Event, EventRegistration
from apps.makerspaces.membership_activation import _activate_membership
from apps.makerspaces.models import (
    MakerspaceMembership,
    MakerspaceRole,
)
from apps.payments.models import Payment
from tests.payments.test_models import configured_settings
from tests.return_helpers import make_member, make_space, make_user


pytestmark = pytest.mark.django_db


def enable_payments(makerspace, domain, *, currency="usd"):
    # The A6 master switch is an additive AND, so a per-domain feature alone is
    # no longer enough to charge.
    makerspace.enabled_features = ["payments.enabled", f"payments.{domain}"]
    makerspace.save(update_fields=["enabled_features", "updated_at"])
    settings = configured_settings(makerspace)
    settings.default_currency = currency
    settings.save(update_fields=["default_currency"])


def chargeable_space(makerspace, actor, *, mode="instant", amount="12.50"):
    return BookableSpace.objects.create(
        makerspace=makerspace,
        created_by=actor,
        name="Paid room",
        approval_mode=mode,
        payment_amount=amount,
    )


def with_phone(user):
    user.phone = "1"
    user.save(update_fields=["phone"])
    return user


def booking_times():
    start = timezone.now() + timedelta(days=1)
    return start, start + timedelta(hours=1)


def test_instant_and_approved_bookings_charge_without_checkout_blocking(
    monkeypatch,
    django_capture_on_commit_callbacks,
):
    makerspace = make_space("paid-bookings")
    actor = with_phone(make_member("paid-booker", makerspace))
    enable_payments(makerspace, "bookings", currency="eur")
    monkeypatch.setattr(
        booking_payments,
        "create_checkout",
        lambda _payment: (_ for _ in ()).throw(RuntimeError("Stripe down")),
    )

    start, end = booking_times()
    with django_capture_on_commit_callbacks(execute=True):
        instant = services_bookings.create_booking(
            chargeable_space(makerspace, actor),
            starts_at=start,
            ends_at=end,
            member=actor,
            actor=actor,
        )
    assert instant.status == Booking.Status.CONFIRMED
    instant_payment = Payment.objects.get(subject_id=instant.pk)
    assert (instant_payment.amount, instant_payment.currency) == (12.50, "eur")

    pending = services_bookings.create_booking(
        chargeable_space(makerspace, actor, mode="approve"),
        starts_at=start + timedelta(hours=2),
        ends_at=end + timedelta(hours=2),
        member=actor,
        actor=actor,
    )
    assert pending.status == Booking.Status.PENDING
    assert not Payment.objects.filter(subject_id=pending.pk).exists()
    with django_capture_on_commit_callbacks(execute=True):
        approved = services_bookings.approve_booking(pending, actor=actor)
    assert approved.status == Booking.Status.CONFIRMED
    assert Payment.objects.filter(subject_id=pending.pk).count() == 1


def test_event_charges_registered_and_promoted_once(monkeypatch):
    makerspace = make_space("paid-events")
    first = with_phone(make_member("paid-event-first", makerspace))
    second = with_phone(make_member("paid-event-second", makerspace))
    enable_payments(makerspace, "events")
    monkeypatch.setattr(event_payments, "create_checkout", lambda _payment: None)
    start = timezone.now() + timedelta(days=1)
    event = Event.objects.create(
        makerspace=makerspace,
        title="Paid event",
        starts_at=start,
        ends_at=start + timedelta(hours=2),
        capacity=1,
        is_public=True,
        status=Event.Status.PUBLISHED,
        payment_amount="7.00",
    )

    registered = event_services.register(event, member=first, actor=first)
    waitlisted = event_services.register(event, member=second, actor=second)
    assert registered.status == EventRegistration.Status.REGISTERED
    assert waitlisted.status == EventRegistration.Status.WAITLISTED
    assert Payment.objects.filter(subject_id=registered.pk).count() == 1
    assert not Payment.objects.filter(subject_id=waitlisted.pk).exists()

    event_services.cancel_registration(registered, actor=first)
    assert Payment.objects.get(subject_id=registered.pk).status == Payment.Status.CANCELED
    waitlisted.refresh_from_db()
    assert waitlisted.status == EventRegistration.Status.REGISTERED
    assert Payment.objects.filter(subject_id=waitlisted.pk).count() == 1


def test_membership_activation_and_legacy_reactivation_reuse_one_payment(monkeypatch):
    makerspace = make_space("paid-membership")
    manager = make_member("paid-membership-manager", makerspace)
    user = make_user("paid-membership-user", access_status=User.AccessStatus.ACTIVE)
    makerspace.membership_dues_amount = "20.00"
    makerspace.save(update_fields=["membership_dues_amount", "updated_at"])
    enable_payments(makerspace, "membership")
    role = MakerspaceRole.objects.filter(
        makerspace=makerspace,
        is_default=True,
    ).order_by("id").first()
    monkeypatch.setattr(
        "apps.makerspaces.membership_payments.create_checkout",
        lambda _payment: None,
    )

    membership = _activate_membership(
        manager, makerspace, user, role, source="join"
    )
    payment = Payment.objects.get(subject_id=membership.pk)
    membership.status = "revoked"
    membership.save(update_fields=["status"])
    reactivated = _activate_membership(
        manager, makerspace, user, role, source="join"
    )
    _activate_membership(manager, makerspace, user, role, source="approval")

    assert reactivated.status == "active"
    assert Payment.objects.filter(subject_id=membership.pk).count() == 1
    assert Payment.objects.get(pk=payment.pk).status == Payment.Status.PENDING


def test_zero_feature_credentials_and_membership_module_disable_charging(monkeypatch):
    monkeypatch.setattr(booking_payments, "create_checkout", lambda _payment: None)
    actor_and_spaces = []
    for suffix in ("zero", "feature", "credentials"):
        makerspace = make_space(f"payments-off-{suffix}")
        actor = with_phone(make_member(f"payments-off-{suffix}-member", makerspace))
        actor_and_spaces.append((makerspace, actor))
    zero, feature_off, credentials_off = actor_and_spaces
    enable_payments(zero[0], "bookings")
    configured_settings(feature_off[0])
    credentials_off[0].enabled_features = ["payments.enabled", "payments.bookings"]
    credentials_off[0].save(update_fields=["enabled_features", "updated_at"])

    for makerspace, actor in actor_and_spaces:
        start, end = booking_times()
        booking = services_bookings.create_booking(
            chargeable_space(
                makerspace,
                actor,
                amount="0" if makerspace == zero[0] else "5",
            ),
            starts_at=start,
            ends_at=end,
            member=actor,
            actor=actor,
        )
        assert not Payment.objects.filter(subject_id=booking.pk).exists()

    membership_space = make_space("payments-off-membership-module")
    membership_actor = make_member(
        "payments-off-membership-member",
        membership_space,
    )
    membership_space.membership_dues_amount = "9.00"
    enable_payments(membership_space, "membership")
    membership_space.enabled_modules = [
        module
        for module in membership_space.enabled_modules
        if module != "membership"
    ]
    membership_space.save(update_fields=["enabled_modules", "updated_at"])
    membership = MakerspaceMembership.objects.get(
        makerspace=membership_space,
        user=membership_actor,
    )
    from apps.makerspaces.membership_payments import create_for_active_membership

    assert create_for_active_membership(membership, membership_actor) is None


@pytest.mark.django_db(transaction=True)
def test_concurrent_booking_helper_is_idempotent(monkeypatch):
    makerspace = make_space("payment-concurrent-booking")
    actor = make_member("payment-concurrent-member", makerspace)
    enable_payments(makerspace, "bookings")
    booking = Booking.objects.create(
        space=chargeable_space(makerspace, actor, amount="4.00"),
        member=actor,
        name=actor.username,
        email=actor.email,
        phone="1",
        starts_at=booking_times()[0],
        ends_at=booking_times()[1],
    )
    monkeypatch.setattr(booking_payments, "create_checkout", lambda _payment: None)

    def create():
        close_old_connections()
        row = Booking.objects.select_related("space__makerspace", "member").get(
            pk=booking.pk
        )
        result = booking_payments.create_for_confirmed_booking(row, actor)
        close_old_connections()
        return result.pk if result else None

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _index: create(), range(2)))
    assert Payment.objects.filter(
        subject_type=Payment.SubjectType.BOOKING,
        subject_id=booking.pk,
    ).count() == 1


def test_new_payment_subjects_require_same_tenant_and_membership_user():
    makerspace = make_space("payment-subject-validation")
    other = make_space("payment-subject-validation-other")
    actor = make_member("payment-subject-validation-member", makerspace)
    outsider = make_member("payment-subject-validation-outsider", other)
    now = timezone.now() + timedelta(days=1)
    booking = Booking.objects.create(
        space=chargeable_space(makerspace, actor),
        member=actor,
        name=actor.username,
        email=actor.email,
        phone="1",
        starts_at=now,
        ends_at=now + timedelta(hours=1),
    )
    membership = MakerspaceMembership.objects.get(
        makerspace=makerspace,
        user=actor,
    )

    with pytest.raises(ValidationError):
        Payment.objects.create(
            makerspace=other,
            subject_type=Payment.SubjectType.BOOKING,
            subject_id=booking.pk,
            member=actor,
            amount="1.00",
            currency="usd",
            created_by=actor,
        )
    with pytest.raises(ValidationError):
        Payment.objects.create(
            makerspace=makerspace,
            subject_type=Payment.SubjectType.MAKERSPACE_MEMBERSHIP,
            subject_id=membership.pk,
            member=outsider,
            amount="1.00",
            currency="usd",
            created_by=actor,
        )
