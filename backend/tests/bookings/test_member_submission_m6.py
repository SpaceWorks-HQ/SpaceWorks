from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.bookings.models import BookableSpace
from apps.events.models import Event, EventRegistration
from apps.makerspaces.models import Makerspace, MakerspaceMembership, MakerspaceRole
from apps.makerspaces.waiver_services import accept_waiver, publish_waiver
from apps.presence import services as presence_services


pytestmark = pytest.mark.django_db


def member(space):
    user = User.objects.create_user(
        username="m6-member", password="password", display_name="Account Name",
        email="account@example.test", phone="1234567890",
    )
    role = MakerspaceRole.objects.get(makerspace=space, slug="member")
    membership = MakerspaceMembership.objects.create(
        makerspace=space, user=user, assigned_role=role, role="custom",
    )
    return user, membership


def authenticated_client(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


def activate(user, membership, space):
    publish_waiver(user, space, "Terms", "v1")
    accept_waiver(membership)
    presence_services.start_session(user, space, 60)


def booking_payload():
    start = timezone.now() + timedelta(days=1)
    return {"starts_at": start.isoformat(), "ends_at": (start + timedelta(hours=1)).isoformat()}


def test_booking_submission_enforces_all_gate_states_and_snapshots_member():
    space = Makerspace.objects.create(name="M6 Booking", slug="m6-booking")
    bookable = BookableSpace.objects.create(makerspace=space, name="Room", is_public=True)
    user, membership = member(space)
    url = reverse("public-booking-submit", kwargs={"makerspace_slug": space.slug, "public_token": bookable.public_token})

    assert APIClient().post(url, booking_payload(), format="json").status_code == 401
    outsider = User.objects.create_user(username="m6-outsider", password="password")
    response = authenticated_client(outsider).post(url, booking_payload(), format="json")
    assert response.status_code == 403 and response.data["code"] == "membership_required"
    publish_waiver(user, space, "Terms", "v1")
    response = authenticated_client(user).post(url, booking_payload(), format="json")
    assert response.status_code == 403 and response.data["code"] == "waiver_acceptance_required"

    accept_waiver(membership)
    # Booking is a plan to attend: no open presence session is required.
    response = authenticated_client(user).post(url, booking_payload(), format="json")
    assert response.status_code == 201
    booking = bookable.bookings.get()
    assert (booking.member, booking.name, booking.email, booking.phone) == (user, "Account Name", "account@example.test", "1234567890")


def test_booking_honeypot_is_a_member_gated_noop():
    space = Makerspace.objects.create(name="M6 Honeypot", slug="m6-honeypot")
    bookable = BookableSpace.objects.create(makerspace=space, name="Room", is_public=True)
    user, membership = member(space)
    activate(user, membership, space)
    url = reverse("public-booking-submit", kwargs={"makerspace_slug": space.slug, "public_token": bookable.public_token})
    response = authenticated_client(user).post(url, {"website": "bot.example"}, format="json")
    assert response.status_code == 201
    assert not bookable.bookings.exists()


def test_event_registration_is_owned_by_member_and_active_member_is_unique():
    space = Makerspace.objects.create(name="M6 Event", slug="m6-event")
    event = Event.objects.create(
        makerspace=space, title="Workshop", is_public=True, status=Event.Status.PUBLISHED,
        starts_at=timezone.now() + timedelta(days=1), ends_at=timezone.now() + timedelta(days=1, hours=1),
    )
    user, membership = member(space)
    activate(user, membership, space)
    url = reverse("public-event-register", kwargs={"makerspace_slug": space.slug, "public_token": event.public_token})
    client = authenticated_client(user)
    assert client.post(url, {}, format="json").status_code == 201
    registration = event.registrations.get()
    assert registration.member == user
    assert (registration.name, registration.email, registration.phone) == ("Account Name", "account@example.test", "1234567890")
    assert client.post(url, {}, format="json").status_code == 201
    assert EventRegistration.objects.filter(event=event, member=user).count() == 1
