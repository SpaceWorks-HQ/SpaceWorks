from datetime import timedelta
from importlib import import_module
from uuid import uuid4

import pytest
from django.apps import apps as django_apps
from django.db import IntegrityError, connection, transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.bookings.models import BookableSpace, Booking
from apps.makerspaces.models import Makerspace

pytestmark = pytest.mark.django_db


def make_makerspace(slug):
    return Makerspace.objects.create(name=slug, slug=slug)


def make_space(makerspace, **overrides):
    defaults = {"makerspace": makerspace, "name": "Development Room"}
    defaults.update(overrides)
    return BookableSpace.objects.create(**defaults)


def make_booking(space, **overrides):
    starts_at = timezone.now()
    defaults = {
        "space": space,
        "name": "Ada Lovelace",
        "email": "ada@example.com",
        "phone": "+91 99999 00000",
        "starts_at": starts_at,
        "ends_at": starts_at + timedelta(hours=1),
    }
    defaults.update(overrides)
    return Booking.objects.create(**defaults)


def test_space_defaults_are_other_unlimited_private_active_and_image_null():
    space = make_space(make_makerspace("booking-defaults"))

    assert space.kind == BookableSpace.Kind.OTHER
    assert space.capacity == 0
    assert space.is_public is False
    assert space.show_public_availability is False
    assert space.show_public_booker_names is False
    assert space.is_active is True
    assert space.image_key is None
    assert space.approval_mode == BookableSpace.ApprovalMode.INSTANT
    assert space.custom_form is None
    assert space.requester_notifications_enabled is None
    assert space.makerspace.booking_requester_notifications_enabled is False


def test_booking_defaults_to_confirmed_with_no_custom_answers():
    booking = make_booking(make_space(make_makerspace('booking-answer-defaults')))

    assert booking.status == Booking.Status.CONFIRMED
    assert booking.custom_answers is None


def test_all_space_kinds_and_booking_statuses_round_trip():
    space = make_space(make_makerspace("booking-choices"))
    booking = make_booking(space)

    for kind in BookableSpace.Kind.values:
        space.kind = kind
        space.save(update_fields=["kind"])
        space.refresh_from_db()
        assert space.kind == kind

    for status in Booking.Status.values:
        booking.status = status
        booking.save(update_fields=["status"])
        booking.refresh_from_db()
        assert booking.status == status


def test_database_rejects_negative_capacity_and_invalid_booking_intervals():
    makerspace = make_makerspace("booking-constraints")
    space = make_space(makerspace)
    starts_at = timezone.now()

    with pytest.raises(IntegrityError), transaction.atomic():
        make_space(makerspace, name="Invalid capacity", capacity=-1)

    for ends_at in (starts_at, starts_at - timedelta(seconds=1)):
        with pytest.raises(IntegrityError), transaction.atomic():
            make_booking(space, starts_at=starts_at, ends_at=ends_at)


def test_delete_cascades_and_creator_delete_sets_null():
    creator = User.objects.create_user(username="booking-creator")
    makerspace = make_makerspace("booking-delete-behavior")
    first_space = make_space(makerspace, created_by=creator)
    first_booking = make_booking(first_space)
    second_space = make_space(makerspace, name="Second")
    second_booking = make_booking(second_space)

    creator.delete()
    first_space.refresh_from_db()
    assert first_space.created_by is None

    second_space.delete()
    assert not Booking.objects.filter(pk=second_booking.pk).exists()

    # H4's tenant fence intentionally has a PROTECT FK.  Normal deletion is
    # rejected; the makerspace purge path removes the fence under its scoped
    # immutable-delete GUC before deleting the tenant graph.
    from apps.encryption.models import PiiMakerspaceWriteFence

    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute("SET LOCAL app.allow_immutable_delete = 'on'")
        PiiMakerspaceWriteFence.objects.filter(makerspace=makerspace).delete()
        makerspace.delete()
    assert not BookableSpace.objects.filter(pk=first_space.pk).exists()
    assert not Booking.objects.filter(pk=first_booking.pk).exists()


def test_public_tokens_are_generated_unique_immutable_and_not_internal_ids():
    makerspace = make_makerspace("booking-public-tokens")
    first_space = make_space(makerspace, name="First")
    second_space = make_space(makerspace, name="Second")
    first_booking = make_booking(first_space)
    second_booking = make_booking(first_space, email="grace@example.com")
    original_space_token = first_space.public_token
    original_booking_token = first_booking.public_token

    assert original_space_token != second_space.public_token
    assert original_booking_token != second_booking.public_token
    assert str(original_space_token) != str(first_space.id)
    assert str(original_booking_token) != str(first_booking.id)

    first_space.public_token = uuid4()
    first_space.save(update_fields=["public_token"])
    first_booking.public_token = uuid4()
    first_booking.space = second_space
    first_booking.save(update_fields=["public_token", "space"])
    first_space.refresh_from_db()
    first_booking.refresh_from_db()

    assert first_space.public_token == original_space_token
    assert first_booking.public_token == original_booking_token
    assert first_booking.space_id == first_space.id
    for model in (BookableSpace, Booking):
        field = model._meta.get_field("public_token")
        assert field.unique is True
        assert field.editable is False


def test_model_ordering_indexes_and_constraints_match_contract():
    assert BookableSpace._meta.ordering == ["name", "id"]
    assert Booking._meta.ordering == ["starts_at", "id"]
    assert {index.name for index in BookableSpace._meta.indexes} == {
        "bookspace_ms_active_idx",
        "bookspace_public_idx",
    }
    assert {constraint.name for constraint in BookableSpace._meta.constraints} == {
        "bookspace_capacity_nonnegative",
        "bookspace_min_duration_positive",
        "bookspace_max_duration_gte_min",
        "bookspace_advance_positive",
        "bookspace_payment_nonnegative",
    }
    assert {index.name for index in Booking._meta.indexes} == {
        "booking_space_status_idx",
        "booking_space_end_idx",
    }
    assert {constraint.name for constraint in Booking._meta.constraints} == {
        "booking_end_after_start"
    }


def test_identity_fields_are_normalized():
    space = make_space(
        make_makerspace("booking-normalization"),
        name="  Development Room  ",
    )
    booking = make_booking(
        space,
        name="  Ada Lovelace  ",
        email="  ADA@Example.COM  ",
        phone="  +91 99999 00000  ",
    )

    assert space.name == "Development Room"
    assert booking.name == "Ada Lovelace"
    assert booking.email == "ada@example.com"
    assert booking.phone == "+91 99999 00000"


def test_bookings_module_migration_is_idempotent_and_reverse_is_targeted():
    migration = import_module(
        "apps.makerspaces.migrations.0033_enable_bookings_module"
    )
    first = Makerspace.objects.create(
        name="Migration One",
        slug="bookings-migration-one",
        enabled_modules=["custom", "events"],
    )
    second = Makerspace.objects.create(
        name="Migration Two",
        slug="bookings-migration-two",
        enabled_modules=["bookings", "another-custom"],
    )

    migration.enable_bookings(django_apps, None)
    migration.enable_bookings(django_apps, None)
    first.refresh_from_db()
    second.refresh_from_db()
    assert first.enabled_modules == ["custom", "events", "bookings"]
    assert second.enabled_modules == ["bookings", "another-custom"]

    migration.disable_bookings(django_apps, None)
    first.refresh_from_db()
    second.refresh_from_db()
    assert first.enabled_modules == ["custom", "events"]
    assert second.enabled_modules == ["another-custom"]


def test_bookings_is_an_installable_module():
    # Modules are opt-in, so `bookings` is no longer on by default. It must still be a
    # registered module that the `everything` profile installs. (The old assertion
    # pinned its position within enabled_modules, which canonicalization sorts anyway.)
    from apps.makerspaces.models import DEFAULT_ENABLED_MODULES
    from apps.makerspaces.module_profiles import EVERYTHING, profile_modules

    assert "bookings" not in DEFAULT_ENABLED_MODULES
    assert "bookings" in profile_modules(EVERYTHING)


def test_booking_status_data_migration_and_lossy_reverse():
    migration = import_module(
        'apps.bookings.migrations.0003_public_booking_custom_forms'
    )
    space = make_space(make_makerspace('booking-status-migration'))
    confirmed = make_booking(space, email='confirmed@example.com')
    pending = make_booking(space, email='pending@example.com')
    rejected = make_booking(space, email='rejected@example.com')

    Booking.objects.filter(pk=confirmed.pk).update(status='booked')
    migration.booked_to_confirmed(django_apps, None)
    confirmed.refresh_from_db()
    assert confirmed.status == Booking.Status.CONFIRMED

    Booking.objects.filter(pk=pending.pk).update(status=Booking.Status.PENDING)
    Booking.objects.filter(pk=rejected.pk).update(status=Booking.Status.REJECTED)
    migration.confirmed_to_booked(django_apps, None)
    confirmed.refresh_from_db()
    pending.refresh_from_db()
    rejected.refresh_from_db()
    assert confirmed.status == 'booked'
    assert pending.status == Booking.Status.CANCELLED
    assert rejected.status == Booking.Status.CANCELLED
