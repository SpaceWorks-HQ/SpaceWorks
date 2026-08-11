"""Phase 3 -- a visiting member must be able to find and pay a host-raised charge.

A collaborative event is hosted by A, so its `Payment` is created under A: ownership decides
which Stripe account is charged, and that is correct. But the member reached it through B, has
no membership at A, and every member payment surface filtered on `makerspace_id`. The charge
therefore existed and was undiscoverable -- A's history 403'd them and B's filtered it out.

The widening is keyed on durable provenance, so it can only surface a charge the member
incurred THROUGH this space. It must never become "every payment this user has anywhere".
"""

from decimal import Decimal

import pytest
from django.urls import reverse

from apps.payments.member_scope import member_payment_queryset
from apps.payments.models import Payment
from tests.events.collab_helpers import (
    client_for,
    collaborate,
    make_event,
    make_member,
    make_space,
)

pytestmark = pytest.mark.django_db


def charge(makerspace, member, subject_id, amount="10.00"):
    return Payment.objects.create(
        makerspace=makerspace,
        member=member,
        created_by=member,
        subject_type=Payment.SubjectType.EVENT_REGISTRATION,
        subject_id=subject_id,
        amount=Decimal(amount),
        currency="usd",
        status=Payment.Status.PENDING,
    )


def local_registration(space, member):
    """A registration hosted BY `space`, so a Payment under `space` is a valid subject.

    `Payment.clean()` checks the subject belongs to the payment's makerspace, so these tests
    use real rows rather than invented subject ids -- that validation is worth keeping.
    """
    from apps.events.models import EventRegistration

    event = make_event(space, is_public=True, title=f"{space.slug} own event")
    return EventRegistration.objects.create(
        event=event, member=member, name=member.display_name or member.username,
        email=member.email, phone="1234567890",
        registered_via_makerspace=space,
    )


def history_url(space):
    return reverse("member-payment-history", kwargs={"makerspace_id": space.pk})


def test_a_host_raised_charge_is_visible_from_the_space_it_was_incurred_through():
    host, partner = make_space("host"), make_space("partner")
    event = make_event(host, is_public=False)
    collaborate(event, partner)
    member = make_member(partner, "visitor")
    registered = client_for(member).post(
        reverse(
            "member-collaborative-event-register",
            kwargs={"makerspace_id": partner.pk, "pk": event.pk},
        ),
        {},
        format="json",
    )
    assert registered.status_code == 201
    from apps.events.models import EventRegistration

    registration = EventRegistration.objects.get(event=event, member=member)
    payment = charge(host, member, registration.pk)

    rows = member_payment_queryset(member, partner.pk)

    assert payment in list(rows)


def test_the_widening_does_not_flatten_an_unrelated_spaces_charges():
    """The narrowness is the point: provenance, not "everything this user owes"."""
    host, partner, other = make_space("host"), make_space("partner"), make_space("other")
    event = make_event(host, is_public=False)
    collaborate(event, partner)
    member = make_member(partner, "visitor")
    make_member(other, "visitor-other", user=member)
    # A charge at `other` that this member never incurred through `partner`.
    unrelated = charge(other, member, local_registration(other, member).pk)

    rows = list(member_payment_queryset(member, partner.pk))

    assert unrelated not in rows


def test_another_members_charge_is_never_visible():
    host, partner = make_space("host"), make_space("partner")
    event = make_event(host, is_public=False)
    collaborate(event, partner)
    mine = make_member(partner, "mine")
    theirs = make_member(partner, "theirs")
    theirs_charge = charge(partner, theirs, local_registration(partner, theirs).pk)

    assert theirs_charge not in list(member_payment_queryset(mine, partner.pk))


def test_a_same_space_charge_still_works_unchanged():
    space = make_space("solo")
    member = make_member(space, "member")
    own = charge(space, member, local_registration(space, member).pk)

    assert own in list(member_payment_queryset(member, space.pk))


def test_history_endpoint_reaches_the_partner_hosted_charge():
    host, partner = make_space("host"), make_space("partner")
    event = make_event(host, is_public=False)
    collaborate(event, partner)
    member = make_member(partner, "visitor")
    client = client_for(member)
    client.post(
        reverse(
            "member-collaborative-event-register",
            kwargs={"makerspace_id": partner.pk, "pk": event.pk},
        ),
        {},
        format="json",
    )
    from apps.events.models import EventRegistration

    registration = EventRegistration.objects.get(event=event, member=member)
    charge(host, member, registration.pk)

    response = client.get(history_url(partner))

    assert response.status_code == 200
    assert len(response.data) == 1
