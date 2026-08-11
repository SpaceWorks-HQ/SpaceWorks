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


def charge(makerspace, member, subject_id, amount="10.00", via_makerspace=None):
    """A raw Payment row.

    `via_makerspace` is what the production path stamps at creation
    (`service_payments._get_or_create`), and it is what the second arm of
    `member_payment_queryset` now keys on -- routing moved OFF the registration's
    provenance so that a module purge, which deliberately clears that provenance, can no
    longer strand a receipt or a payable debt. Tests that fabricate a row therefore have to
    supply it, exactly as the real creation path does.
    """
    return Payment.objects.create(
        makerspace=makerspace,
        member=member,
        created_by=member,
        subject_type=Payment.SubjectType.EVENT_REGISTRATION,
        subject_id=subject_id,
        amount=Decimal(amount),
        currency="usd",
        status=Payment.Status.PENDING,
        via_makerspace=via_makerspace,
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
    payment = charge(host, member, registration.pk, via_makerspace=partner)

    rows = member_payment_queryset(member, partner.pk)

    assert payment in list(rows)


def test_the_widening_does_not_flatten_an_unrelated_spaces_charges():
    """The narrowness is the point: provenance, not "everything this user owes"."""
    host, partner, other = make_space("host"), make_space("partner"), make_space("other")
    event = make_event(host, is_public=False)
    collaborate(event, partner)
    member = make_member(partner, "visitor")
    make_member(other, "visitor-other", user=member)
    # A charge at `other` that this member never incurred through `partner`. Routed to
    # `other`, not left unrouted -- an unrouted row is excluded by the second arm no matter
    # what, so it would pass this assertion without proving any narrowness at all.
    unrelated = charge(
        other, member, local_registration(other, member).pk, via_makerspace=other,
    )

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
    charge(host, member, registration.pk, via_makerspace=partner)

    response = client.get(history_url(partner))

    assert response.status_code == 200
    assert len(response.data) == 1


def test_the_real_creation_path_stamps_the_routing():
    """The wiring, not just the query.

    `create_for_registered_registration` swallows every exception and returns None, so a
    mismatch between its call and `create_payment`'s signature would not raise -- it would
    silently stop creating charges altogether, with registration still returning 201. Only a
    test that drives the real path can see that, which is why this one does not fabricate the
    Payment the way `charge()` does.
    """
    from apps.events.models import EventRegistration
    from apps.events.service_payments import create_for_registered_registration
    from tests.payments.test_models import configured_settings

    host, partner = make_space("host"), make_space("partner")
    event = make_event(host, is_public=False)
    event.payment_amount = Decimal("8.00")
    event.save(update_fields=["payment_amount"])
    host.enabled_features = ["payments.enabled", "payments.events"]
    host.save(update_fields=["enabled_features", "updated_at"])
    settings = configured_settings(host)
    settings.default_currency = "usd"
    settings.save(update_fields=["default_currency"])
    collaborate(event, partner)
    member = make_member(partner, "visitor")
    client_for(member).post(
        reverse(
            "member-collaborative-event-register",
            kwargs={"makerspace_id": partner.pk, "pk": event.pk},
        ),
        {},
        format="json",
    )
    registration = EventRegistration.objects.get(event=event, member=member)

    payment = create_for_registered_registration(registration, member)

    assert payment is not None, "the charge was never created -- check create_payment's signature"
    assert payment.makerspace_id == host.pk, "ownership decides which Stripe account is charged"
    assert payment.via_makerspace_id == partner.pk
    assert payment in list(member_payment_queryset(member, partner.pk))


def test_purging_events_at_the_collaborator_keeps_the_charge_payable():
    """The P1 regression guard.

    A purge clears `registered_via_makerspace` by design -- activity history is exactly what
    it destroys. But the money must survive it: the host still 403s this member, so if the
    collaborator's member area also stops matching, a pending charge becomes impossible to
    settle and a paid one impossible to prove.
    """
    from apps.events.models import EventRegistration
    from apps.makerspaces.module_purge_collectors import events_delete

    host, partner = make_space("host"), make_space("partner")
    event = make_event(host, is_public=False)
    collaborate(event, partner)
    member = make_member(partner, "visitor")
    client_for(member).post(
        reverse(
            "member-collaborative-event-register",
            kwargs={"makerspace_id": partner.pk, "pk": event.pk},
        ),
        {},
        format="json",
    )
    registration = EventRegistration.objects.get(event=event, member=member)
    payment = charge(host, member, registration.pk, via_makerspace=partner)

    # The real collector, not a hand-rolled imitation of it.
    events_delete(partner, None)

    registration.refresh_from_db()
    assert registration.registered_via_makerspace_id is None, "the purge must still clear provenance"
    assert payment in list(member_payment_queryset(member, partner.pk))


def test_a_waitlisted_registration_promoted_after_a_purge_is_still_payable():
    """The delayed-charge case: no Payment exists yet when the purge runs.

    A waitlisted registration is charged only when `_promote()` lifts it to REGISTERED. If
    the collaborator purges `events` in between, `registered_via_makerspace` is already NULL
    by then, and falling back to the host would stamp the charge with a space where the
    visiting member holds no membership -- refused there, filtered out at home, payable from
    neither. `Payment.via_makerspace` cannot rescue this one: at purge time there is no
    Payment row to carry the routing, which is why the registration keeps its own copy.
    """
    from apps.events import services
    from apps.events.models import EventRegistration
    from apps.makerspaces.module_purge_collectors import events_delete
    from tests.payments.test_models import configured_settings

    host, partner = make_space("host"), make_space("partner")
    event = make_event(host, is_public=False)
    event.capacity = 1
    event.payment_amount = Decimal("8.00")
    event.save(update_fields=["capacity", "payment_amount"])
    host.enabled_features = ["payments.enabled", "payments.events"]
    host.save(update_fields=["enabled_features", "updated_at"])
    settings = configured_settings(host)
    settings.default_currency = "usd"
    settings.save(update_fields=["default_currency"])
    collaborate(event, partner)

    taker = make_member(partner, "taker")
    client_for(taker).post(
        reverse(
            "member-collaborative-event-register",
            kwargs={"makerspace_id": partner.pk, "pk": event.pk},
        ),
        {}, format="json",
    )
    waiter = make_member(partner, "waiter")
    client_for(waiter).post(
        reverse(
            "member-collaborative-event-register",
            kwargs={"makerspace_id": partner.pk, "pk": event.pk},
        ),
        {}, format="json",
    )
    waitlisted = EventRegistration.objects.get(event=event, member=waiter)
    assert waitlisted.status == EventRegistration.Status.WAITLISTED
    assert not Payment.objects.filter(subject_id=waitlisted.pk).exists()

    # The partner purges `events` BEFORE the promotion that raises the charge.
    events_delete(partner, None)
    waitlisted.refresh_from_db()
    assert waitlisted.registered_via_makerspace_id is None, "provenance must still be purged"

    # A seat frees up and the waiter is promoted, creating the charge only now.
    services.cancel_registration(
        EventRegistration.objects.get(event=event, member=taker), actor=taker,
    )

    waitlisted.refresh_from_db()
    payment = Payment.objects.filter(subject_id=waitlisted.pk).first()
    assert payment is not None, "promotion should have raised the charge"
    assert payment.makerspace_id == host.pk
    assert payment.via_makerspace_id == partner.pk, "routed to a space the member can reach"
    assert payment in list(member_payment_queryset(waiter, partner.pk))
