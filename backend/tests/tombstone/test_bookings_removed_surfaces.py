"""apps/bookings under the tombstone profile (plan B5/B6, phase 14).

The last app in the B6 sequence, and the one with the widest retention surface. Bookings
owns a module key, so the console tab drops itself, and the staff relocation is the
ordinary half. What is specific here is that a booking is *three* kinds of retained
thing at once: it holds encrypted PII (`bookings.Booking`), it is a payment subject, and
its bookable spaces own objects in the **public** image bucket -- the only separable app
whose purge plan has to name public keys as well as rows.

Public image keys are the quiet one. They are not reachable from a purge that walks rows
alone, so if `public_image_keys` stopped being registered the rows would still delete and
the objects would stay in a world-readable bucket with nothing left able to name them.
"""

import pytest
from django.contrib import admin
from django.urls import Resolver404, resolve
from rest_framework.test import APIClient

from apps.bookings.models import BookableSpace, Booking
from apps.makerspaces.models import Makerspace
from apps.makerspaces.module_registry import module_available
from apps.makerspaces.platform import available_modules
from apps.separability.registry import pii_fields_for, purge_plan_for, runtime_active

pytestmark = pytest.mark.django_db


# --------------------------------------------------------------------------
# Surfaces: gone.
# --------------------------------------------------------------------------

def test_the_app_is_registered_as_inactive():
    assert runtime_active("bookings") is False
    assert module_available("bookings") is False


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/admin/makerspaces/1/spaces/",
        "/api/v1/admin/spaces/1/",
        "/api/v1/admin/spaces/1/deactivate/",
        "/api/v1/admin/spaces/1/image/presign/",
        "/api/v1/admin/spaces/1/image/finalize/",
        "/api/v1/admin/spaces/1/image/",
        "/api/v1/admin/spaces/1/bookings/",
        "/api/v1/admin/spaces/1/booking-rules/",
        "/api/v1/admin/bookings/1/approve/",
        "/api/v1/admin/bookings/1/reject/",
        "/api/v1/admin/bookings/1/cancel/",
        "/api/v1/admin/bookings/1/complete/",
        "/api/v1/admin/bookings/1/no-show/",
    ],
)
def test_no_staff_booking_route_resolves(path):
    with pytest.raises(Resolver404):
        resolve(path)


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/public/demo/spaces/",
        "/api/v1/public/demo/spaces/0e2b1c94-1f5a-4a0b-8f2a-2f1d3c4b5a60/availability/",
        "/api/v1/public/demo/spaces/0e2b1c94-1f5a-4a0b-8f2a-2f1d3c4b5a60/book/",
    ],
)
def test_no_public_booking_route_resolves(path):
    """Public self-booking goes with the same tombstone as the staff half."""
    with pytest.raises(Resolver404):
        resolve(path)


def test_the_neighbours_sharing_both_prefixes_still_resolve():
    """Bookings straddled two shared prefixes; withdrawing it must not take a neighbour.

    Named neighbours are ones no phase withdraws: memberships and roles live in
    `admin_api` and `apps.machines` is the kernel.
    """
    assert resolve("/api/v1/admin/makerspaces/1/memberships").url_name == "admin-membership-list-create"
    assert resolve("/api/v1/admin/makerspaces/1/roles/1").url_name == "admin-role-detail"
    assert resolve("/api/v1/public/demo/machines").url_name == "public-machines"


def test_the_admin_does_not_register_the_models():
    for model in (BookableSpace, Booking):
        assert model not in admin.site._registry


def test_the_openapi_schema_does_not_advertise_bookings():
    response = APIClient().get("/schema/?format=json")

    assert response.status_code == 200
    assert b"/spaces/" not in response.content
    assert b"/bookings/" not in response.content


def test_the_module_is_not_offered_to_the_console():
    space = Makerspace.objects.create(name="tombstoned-bookings", slug="tombstoned-bookings")
    space.enabled_modules = sorted(set(space.enabled_modules) | {"bookings"})
    space.save(update_fields=["enabled_modules"])

    assert "bookings" not in available_modules(space)


# --------------------------------------------------------------------------
# Data and retention: untouched.
# --------------------------------------------------------------------------

def test_booking_rows_are_still_readable():
    space, booking = _seed("retained-bookings")

    assert Booking.objects.get(pk=booking.pk).space_id == space.pk


def test_the_booking_pii_mapping_survives_the_tombstone():
    """The fail-OPEN case: an unmapped model stores plaintext and raises nothing."""
    fields = pii_fields_for("bookings.Booking")

    assert fields, "Booking must stay mapped or its PII silently goes plaintext"
    assert {field.field_name for field in fields} == {"name", "email", "phone", "note"}


def test_the_purge_plan_still_names_rows_pii_and_public_objects():
    """Public image keys are the half nothing else can reconstruct after the rows go."""
    plan = purge_plan_for("bookings")

    assert plan is not None
    assert "bookings.Booking" in plan.pii_labels
    assert plan.public_image_keys is not None


def test_a_historic_booking_payment_is_still_nameable():
    """Payment rows are immutable and generic-keyed, so nothing cascades them.

    A charge taken before the tombstone outlives the surfaces that created it, and
    reconciliation still has to say what it was for.
    """
    from apps.payments.models import Payment
    from apps.payments.subjects import resolve_subject_labels
    from tests.return_helpers import make_user

    space, booking = _seed("retained-bookings-payment")
    payment = Payment.objects.create(
        makerspace=space.makerspace,
        subject_type=Payment.SubjectType.BOOKING,
        subject_id=booking.pk,
        amount="8.50",
        currency="eur",
        created_by=make_user("bookings-tombstone-cashier"),
    )

    labels = resolve_subject_labels([payment])

    assert labels[(Payment.SubjectType.BOOKING, booking.pk)] == space.name


def test_the_booking_model_is_still_a_scoped_pii_model():
    """The mapping above only protects anything while the mixin is still in play."""
    from apps.encryption.mappers import ScopedPiiModelMixin

    assert issubclass(Booking, ScopedPiiModelMixin)


def _seed(slug):
    from datetime import timedelta

    from django.utils import timezone

    from tests.return_helpers import make_space

    makerspace = make_space(slug)
    space = BookableSpace.objects.create(makerspace=makerspace, name=f"{slug}-room")
    now = timezone.now()
    booking = Booking.objects.create(
        space=space,
        name="Ada",
        email="ada@example.com",
        phone="+3512345678",
        starts_at=now,
        ends_at=now + timedelta(hours=1),
    )
    return space, booking
