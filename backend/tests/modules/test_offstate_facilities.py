"""Off-state contracts for the optional bookings and events modules."""

from datetime import timedelta

import pytest
from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.bookings.models import BookableSpace
from apps.events.models import Event
from apps.inventory.models import InventoryProduct
from apps.makerspaces.models import Makerspace, MakerspaceMembership
from apps.makerspaces.module_registry import BY_KEY, core_module_keys
from apps.presence.models import PresenceSession


pytestmark = pytest.mark.django_db

CORE = frozenset(core_module_keys())


@pytest.fixture(autouse=True)
def clear_throttles():
    cache.clear()
    yield
    cache.clear()


def _space(slug, *optional_modules):
    return Makerspace.objects.create(
        name=slug,
        slug=slug,
        enabled_modules=sorted(CORE | set(optional_modules)),
        public_inventory_enabled=True,
    )


def _account(slug):
    return User.objects.create_user(
        username=slug,
        email=f"{slug}@example.test",
        display_name="Facility Member",
        phone="1234567890",
        access_status=User.AccessStatus.ACTIVE,
    )


def _client(user=None):
    client = APIClient()
    if user is not None:
        client.force_authenticate(user)
    return client


def _active_member_client(space, slug):
    user = _account(slug)
    membership = MakerspaceMembership.objects.create(
        makerspace=space,
        user=user,
        status="active",
    )
    now = timezone.now()
    PresenceSession.objects.create(
        member=user,
        makerspace=space,
        membership=membership,
        started_at=now,
        expires_at=now + timedelta(hours=2),
    )
    return user, _client(user)


def _post_booking(space, client):
    bookable = BookableSpace.objects.create(
        makerspace=space,
        name="Project room",
        is_public=True,
        is_active=True,
    )
    starts_at = timezone.now() + timedelta(days=1)
    response = client.post(
        reverse(
            "public-booking-submit",
            kwargs={
                "makerspace_slug": space.slug,
                "public_token": bookable.public_token,
            },
        ),
        {
            "starts_at": starts_at.isoformat(),
            "ends_at": (starts_at + timedelta(hours=1)).isoformat(),
        },
        format="json",
    )
    return bookable, response


def _post_event_registration(space, client):
    starts_at = timezone.now() + timedelta(days=1)
    event = Event.objects.create(
        makerspace=space,
        title="Open workshop",
        starts_at=starts_at,
        ends_at=starts_at + timedelta(hours=2),
        is_public=True,
        status=Event.Status.PUBLISHED,
    )
    response = client.post(
        reverse(
            "public-event-register",
            kwargs={
                "makerspace_slug": space.slug,
                "public_token": event.public_token,
            },
        ),
        {},
        format="json",
    )
    return event, response


def _run_loan_spine(slug, enabled_modules):
    """Exercise public browse through accepted public status, not just a core read."""
    space = Makerspace.objects.create(
        name=slug,
        slug=slug,
        enabled_modules=sorted(enabled_modules),
        public_inventory_enabled=True,
    )
    product = InventoryProduct.objects.create(
        makerspace=space,
        name="Torque wrench",
        total_quantity=3,
        available_quantity=3,
        is_public=True,
    )

    catalogue = _client().get(
        reverse("inventory:public-inventory", args=[space.slug])
    )
    assert catalogue.status_code == 200, catalogue.data

    requester = _account(f"{slug}-requester")
    submitted = _client(requester).post(
        reverse("hardware_requests:request-submit", args=[space.slug]),
        {
            "requested_for": "Facility off-state check",
            "items": [{"product_id": product.pk, "quantity": 1}],
        },
        format="json",
    )
    assert submitted.status_code == 201, submitted.data

    staff = User.objects.create_user(
        username=f"{slug}-staff",
        email=f"{slug}-staff@example.test",
        role=User.Role.SUPERADMIN,
        is_staff=True,
        is_superuser=True,
        access_status=User.AccessStatus.ACTIVE,
    )
    staff_client = _client(staff)
    queued = staff_client.get(
        reverse("hardware_requests:pending-requests", args=[space.pk])
    )
    assert queued.status_code == 200, queued.data
    assert queued.data["count"] == 1

    accepted = staff_client.post(
        reverse(
            "hardware_requests:request-accept",
            args=[queued.data["results"][0]["id"]],
        ),
        {},
        format="json",
    )
    assert accepted.status_code == 200, accepted.data
    assert accepted.data["status"] == "accepted"

    public_status = _client().get(
        reverse(
            "hardware_requests:request-status",
            args=[submitted.data["public_token"]],
        )
    )
    assert public_status.status_code == 200


def test_bookings_off_refuses_the_public_submit():
    space = _space("facilities-bookings-off")
    _, response = _post_booking(
        space,
        _client(_account("facilities-bookings-off-account")),
    )

    assert response.status_code == 400
    assert response.data == {"module": "bookings is disabled for this makerspace."}


def test_events_off_refuses_the_public_registration():
    space = _space("facilities-events-off")
    _, response = _post_event_registration(
        space,
        _client(_account("facilities-events-off-account")),
    )

    assert response.status_code == 400
    assert response.data == {"module": "events is disabled for this makerspace."}


def test_bookings_on_accepts_an_active_present_member():
    space = _space("facilities-bookings-on", "bookings", "membership")
    user, client = _active_member_client(space, "facilities-bookings-on-member")

    bookable, response = _post_booking(space, client)

    assert response.status_code == 201, response.data
    assert bookable.bookings.get().member == user


def test_events_on_accepts_an_active_member():
    space = _space("facilities-events-on", "events", "membership")
    user, client = _active_member_client(space, "facilities-events-on-member")

    event, response = _post_event_registration(space, client)

    assert response.status_code == 201, response.data
    assert event.registrations.get().member == user


def test_bookings_off_leaves_the_core_loan_spine_working():
    """Turning bookings off must not damage request_workflow's account-only fallback."""
    _run_loan_spine("facilities-no-bookings", CORE | {"events"})


def test_events_off_leaves_the_core_loan_spine_working():
    """Turning events off must not damage request_workflow's account-only fallback."""
    _run_loan_spine("facilities-no-events", CORE | {"bookings"})


def test_bookings_either_declares_membership_or_works_when_membership_is_off():
    """A standalone module must remain usable unless its dependency is made explicit."""
    space = _space("facilities-bookings-no-membership", "bookings")
    bookable, response = _post_booking(
        space,
        _client(_account("facilities-bookings-no-membership-account")),
    )

    standalone = "membership" not in BY_KEY["bookings"].requires_modules
    assert not standalone or response.status_code == 201, response.data
    if standalone:
        assert bookable.bookings.count() == 1


def test_events_either_declares_membership_or_works_when_membership_is_off():
    """The events switch cannot promise registration while its only identity path is absent."""
    space = _space("facilities-events-no-membership", "events")
    event, response = _post_event_registration(
        space,
        _client(_account("facilities-events-no-membership-account")),
    )

    standalone = "membership" not in BY_KEY["events"].requires_modules
    assert not standalone or response.status_code == 201, response.data
    if standalone:
        assert event.registrations.count() == 1
