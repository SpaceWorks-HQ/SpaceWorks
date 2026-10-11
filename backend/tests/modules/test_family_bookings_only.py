from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.bookings.models import BookableSpace, Booking
from apps.makerspaces.models import MakerspaceMembership, MakerspaceWaiver
from tests.modules.family_helpers import account, assert_family_bootstrap, client, family_space

pytestmark = pytest.mark.django_db


def test_bookings_only_account_books_ahead_reads_own_history_and_cancels():
    space = family_space("family-bookings", "bookings", "member_accounts")
    borrower = account("family-booker")
    api = client(borrower)
    room = BookableSpace.objects.create(makerspace=space, name="Studio", is_public=True, approval_mode="instant")
    # A waiver on a bookings-only tenant cannot invent a required membership.
    MakerspaceWaiver.objects.create(makerspace=space, version="1", body="Community waiver", is_active=True)
    start = timezone.now() + timedelta(days=7)
    response = api.post(reverse("public-booking-submit", args=[space.slug, room.public_token]), {
        "starts_at": start.isoformat(), "ends_at": (start + timedelta(hours=1)).isoformat(),
    }, format="json")
    assert response.status_code == 201, response.data
    booking = Booking.objects.get(space=room)
    assert booking.member == borrower and booking.status == Booking.Status.CONFIRMED
    assert not MakerspaceMembership.objects.filter(user=borrower).exists()
    assert AuditLog.objects.filter(actor=borrower, action="booking.created").exists()
    history = api.get(reverse("member-booking-list", args=[space.slug]))
    assert history.status_code == 200 and history.data["count"] == 1
    stranger = client(account("family-other-booker"))
    assert stranger.get(reverse("member-booking-list", args=[space.slug])).data["count"] == 0
    url = reverse("member-booking-cancel", args=[space.slug, booking.public_token])
    assert stranger.post(url, {}, format="json").status_code == 404
    assert api.post(url, {}, format="json").status_code == 200
    assert AuditLog.objects.filter(actor=borrower, action="booking.cancelled", target_id=str(booking.pk)).exists()
    assert_family_bootstrap(space, "bookings")


def test_bookings_preserves_existing_membership_waiver_and_restriction():
    space = family_space("family-bookings-waiver", "bookings")
    user = account("family-booking-member")
    MakerspaceMembership.objects.create(makerspace=space, user=user, status="active")
    MakerspaceWaiver.objects.create(makerspace=space, version="1", body="Accept me", is_active=True)
    room = BookableSpace.objects.create(makerspace=space, name="Bench", is_public=True)
    start = timezone.now() + timedelta(days=1)
    body = {"starts_at": start.isoformat(), "ends_at": (start + timedelta(hours=1)).isoformat()}
    url = reverse("public-booking-submit", args=[space.slug, room.public_token])
    response = client(user).post(url, body, format="json")
    assert response.status_code == 403 and response.data["code"] == "waiver_acceptance_required"
    assert client().post(url, body, format="json").status_code == 401
    user.access_status = "restricted"
    user.save(update_fields=["access_status"])
    assert client(user).post(url, body, format="json").status_code == 403
    assert not Booking.objects.filter(space=room).exists()


def test_account_only_booking_refuses_revoked_membership_and_foreign_room_token():
    space = family_space("family-bookings-revoked", "bookings")
    other = family_space("family-bookings-foreign", "bookings")
    user = account("family-revoked-booker")
    MakerspaceMembership.objects.create(makerspace=space, user=user, status="revoked")
    room = BookableSpace.objects.create(makerspace=space, name="Own room", is_public=True)
    foreign = BookableSpace.objects.create(makerspace=other, name="Foreign room", is_public=True)
    start = timezone.now() + timedelta(days=1)
    body = {"starts_at": start.isoformat(), "ends_at": (start + timedelta(hours=1)).isoformat()}
    api = client(user)
    assert api.post(reverse("public-booking-submit", args=[space.slug, room.public_token]), body, format="json").status_code == 403
    assert api.post(reverse("public-booking-submit", args=[space.slug, foreign.public_token]), body, format="json").status_code == 404
    assert not Booking.objects.filter(space=room).exists()
