from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.bookings.models import BookableSpace, Booking
from apps.makerspaces.models import MakerspaceMembership
from apps.payments.models import Payment
from tests.return_helpers import authenticated_client, make_member, make_space


pytestmark = pytest.mark.django_db

URL = "/api/v1/member/archived-payments"


def _archive(makerspace):
    makerspace.archived_at = timezone.now()
    makerspace.save(update_fields=["archived_at", "updated_at"])


def _payment(makerspace, member, *, status=Payment.Status.PENDING):
    membership = MakerspaceMembership.objects.get(
        makerspace=makerspace,
        user=member,
    )
    return Payment.objects.create(
        makerspace=makerspace,
        subject_type=Payment.SubjectType.MAKERSPACE_MEMBERSHIP,
        subject_id=membership.pk,
        member=member,
        amount=Decimal("10.00"),
        currency="usd",
        status=status,
        created_by=member,
        subject_label="Membership dues",
    )


def _paid_booking_payment(makerspace, member):
    now = timezone.now() + timedelta(days=1)
    bookable = BookableSpace.objects.create(makerspace=makerspace, name="Studio")
    booking = Booking.objects.create(
        space=bookable,
        member=member,
        name=member.username,
        email=member.email,
        phone="1",
        starts_at=now,
        ends_at=now + timedelta(hours=1),
    )
    return Payment.objects.create(
        makerspace=makerspace,
        subject_type=Payment.SubjectType.BOOKING,
        subject_id=booking.pk,
        member=member,
        amount=Decimal("20.00"),
        currency="usd",
        status=Payment.Status.PAID_ONLINE,
        created_by=member,
        subject_label="Studio booking",
    )


def test_lists_archived_space_with_correct_payment_counts():
    space = make_space("archived-discovery-counts")
    member = make_member("archived-discovery-counts-member", space)
    _payment(space, member)
    _paid_booking_payment(space, member)
    _archive(space)

    response = authenticated_client(member).get(URL)

    assert response.status_code == 200
    assert response.data == [
        {
            "makerspace": {
                "id": space.pk,
                "slug": space.slug,
                "name": space.name,
            },
            "pending_count": 1,
            "total_count": 2,
        }
    ]


def test_does_not_list_non_archived_space():
    space = make_space("live-discovery-space")
    member = make_member("live-discovery-member", space)
    _payment(space, member)

    response = authenticated_client(member).get(URL)

    assert response.status_code == 200
    assert response.data == []


def test_does_not_list_archived_space_without_caller_payments():
    space = make_space("archived-discovery-empty")
    member = make_member("archived-discovery-empty-member", space)
    _archive(space)

    response = authenticated_client(member).get(URL)

    assert response.status_code == 200
    assert response.data == []


def test_does_not_leak_another_members_spaces_or_counts():
    shared_space = make_space("archived-discovery-shared")
    caller = make_member("archived-discovery-caller", shared_space)
    other = make_member("archived-discovery-other", shared_space)
    _payment(shared_space, caller)
    _payment(shared_space, other)
    _archive(shared_space)

    other_space = make_space("archived-discovery-other-only")
    other_only_member = make_member(
        "archived-discovery-other-only-member", other_space
    )
    _payment(other_space, other_only_member)
    _archive(other_space)

    response = authenticated_client(caller).get(URL)

    assert response.status_code == 200
    assert response.data == [
        {
            "makerspace": {
                "id": shared_space.pk,
                "slug": shared_space.slug,
                "name": shared_space.name,
            },
            "pending_count": 1,
            "total_count": 1,
        }
    ]


def test_rejects_unauthenticated_discovery():
    response = APIClient().get(URL)

    assert response.status_code == 401


def test_checkout_returns_an_archived_payer_to_the_recovery_route():
    """Paying must not land the member on the dead tenant domain they just left.

    `member_area_url` points at the tenant's own member area. For an archived space that is a
    404 -- its custom domain has lost bootstrap and origin trust, and `/m/<slug>/member` cannot
    resolve the tenant either -- so the member paid and arrived nowhere. Both the Stripe branch
    and the provider seam read this one value, so the redirect is fixed for every rail at once.
    """
    from django.test import override_settings

    from apps.makerspaces.models import Makerspace
    from apps.makerspaces.platform import member_area_url, member_payment_return_url

    space = make_space("archived-return-url")
    space.frontend_domain = "closed.example.test"
    space.frontend_domain_status = Makerspace.DomainStatus.VERIFIED
    space.save(update_fields=["frontend_domain", "frontend_domain_status", "updated_at"])

    with override_settings(PUBLIC_APP_BASE_URL="https://central.example.test"):
        assert member_payment_return_url(space) == member_area_url(space)

        _archive(space)

        assert member_area_url(space) == "https://closed.example.test/member"
        assert (
            member_payment_return_url(space)
            == "https://central.example.test/member/archived"
        )


def test_a_collaborative_charge_returns_to_the_space_that_routed_it():
    """Host A owns the charge; member space B is the only area the visitor can sign into.

    `Payment.via_makerspace` is the routing record for a collaborative-event charge. Deriving
    the return URL from the OWNING makerspace sends a visiting member back to a host where
    they hold no membership -- and, when the host is archived but their own space is live,
    dumps them on the archived-recovery page which correctly refuses to list a live space.
    """
    from django.test import override_settings

    from apps.payments.services import member_payment_return_url

    host = make_space("collab-return-host")
    home = make_space("collab-return-home")
    member = make_member("collab-return-member", home)
    payment = _payment(home, member)
    Payment.objects.filter(pk=payment.pk).update(
        makerspace=host, via_makerspace=home
    )
    payment.refresh_from_db()

    with override_settings(PUBLIC_APP_BASE_URL="https://central.example.test"):
        routed = member_payment_return_url(
            payment.via_makerspace or payment.makerspace
        )
        assert routed == "https://central.example.test/m/collab-return-home/member"
        # The owning host would have been the wrong answer.
        assert routed != member_payment_return_url(payment.makerspace)
