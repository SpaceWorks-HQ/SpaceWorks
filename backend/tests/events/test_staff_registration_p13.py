"""Phase 13 -- staff registering a member for an event from the roster.

The point of the phase is that it is the SAME registration service: capacity,
waitlisting, duplicates, the custom form and the charge must all behave identically to
public self-registration, or the console quietly becomes a second state machine.
"""

from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.events.models import Event, EventRegistration
from apps.makerspaces.models import Makerspace, MakerspaceMembership, MakerspaceRole

pytestmark = pytest.mark.django_db


def make_space(slug="event-staff-space"):
    return Makerspace.objects.create(name=slug, slug=slug)


def manager(makerspace):
    user = User.objects.create_user(
        username=f"events-manager-{makerspace.slug}",
        email=f"events-manager-{makerspace.slug}@example.test",
        access_status=User.AccessStatus.ACTIVE,
    )
    MakerspaceMembership.objects.create(
        user=user, makerspace=makerspace,
        role=MakerspaceMembership.Role.SPACE_MANAGER,
        assigned_role=MakerspaceRole.objects.get(makerspace=makerspace, slug="space_manager"),
        status="active",
    )
    return user


def member(makerspace, username="attendee", display_name="Attendee One", phone="+15550100100"):
    user = User.objects.create_user(
        username=f"{username}-{makerspace.slug}",
        email=f"{username}-{makerspace.slug}@example.test",
        display_name=display_name,
        phone=phone,
        access_status=User.AccessStatus.ACTIVE,
    )
    MakerspaceMembership.objects.create(
        user=user, makerspace=makerspace, role=MakerspaceMembership.Role.CUSTOM,
        assigned_role=MakerspaceRole.objects.get(makerspace=makerspace, slug="member"),
        status="active",
    )
    return user


def make_event(makerspace, *, is_public=True, capacity=0, status=Event.Status.PUBLISHED):
    now = timezone.now()
    return Event.objects.create(
        makerspace=makerspace, title="Soldering night",
        starts_at=now + timedelta(hours=1), ends_at=now + timedelta(hours=3),
        capacity=capacity, is_public=is_public, status=status,
    )


def authed(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def register_url(event):
    return f"/api/v1/admin/events/{event.pk}/registrations/"


def roster_url(event):
    return f"/api/v1/admin/events/{event.pk}/eligible-members/"


def test_staff_register_a_member_and_the_details_come_off_the_account():
    space = make_space()
    staff, attendee = manager(space), member(space)
    event = make_event(space)

    response = authed(staff).post(
        register_url(event), {"member_id": attendee.pk}, format="json"
    )
    assert response.status_code == 201, response.data
    registration = EventRegistration.objects.get(event=event)
    assert registration.member_id == attendee.pk
    # Copied off the account, never typed: an attendee list of free text is not an
    # accountability record.
    assert registration.name == "Attendee One"
    assert registration.email == attendee.email


def test_a_members_only_event_can_be_registered_for_by_staff_but_not_the_public():
    """`is_public` says "listed publicly"; a staffer at the door is not the public."""
    from apps.events.exceptions import EventInvalidTransition
    from apps.events import services

    space = make_space()
    staff, attendee = manager(space), member(space)
    event = make_event(space, is_public=False)

    with pytest.raises(EventInvalidTransition):
        services.register(event, member=attendee, actor=None)

    assert authed(staff).post(
        register_url(event), {"member_id": attendee.pk}, format="json"
    ).status_code == 201


def test_an_unpublished_event_is_still_refused():
    space = make_space()
    staff, attendee = manager(space), member(space)
    event = make_event(space, status=Event.Status.DRAFT)

    response = authed(staff).post(
        register_url(event), {"member_id": attendee.pk}, format="json"
    )
    assert response.status_code == 409
    assert not EventRegistration.objects.exists()


def test_capacity_still_waitlists_through_the_staff_path():
    """Same service, so the same capacity rule — not a bypass."""
    space = make_space()
    staff = manager(space)
    first = member(space, username="first", display_name="First")
    second = member(space, username="second", display_name="Second")
    event = make_event(space, capacity=1)
    client = authed(staff)

    assert client.post(register_url(event), {"member_id": first.pk}, format="json").data[
        "status"
    ] == EventRegistration.Status.REGISTERED
    assert client.post(register_url(event), {"member_id": second.pk}, format="json").data[
        "status"
    ] == EventRegistration.Status.WAITLISTED


def test_registering_twice_is_a_conflict():
    space = make_space()
    staff, attendee = manager(space), member(space)
    event = make_event(space)
    client = authed(staff)

    assert client.post(register_url(event), {"member_id": attendee.pk}, format="json").status_code == 201
    # The typed `duplicate_registration` 400 the public path already returns — the same
    # exception map, because it is the same service.
    repeat = client.post(register_url(event), {"member_id": attendee.pk}, format="json")
    assert repeat.status_code == 400
    assert repeat.data.get("code") == "duplicate_registration"


def test_an_account_without_a_number_can_be_registered_with_one_supplied():
    """`EventRegistration.phone` is non-blank, so this would be a dead end otherwise."""
    space = make_space()
    staff = manager(space)
    attendee = member(space, phone="")
    event = make_event(space)
    client = authed(staff)

    refused = client.post(register_url(event), {"member_id": attendee.pk}, format="json")
    assert refused.status_code == 400
    assert "phone" in refused.data

    accepted = client.post(
        register_url(event),
        {"member_id": attendee.pk, "phone": "+15550199000"},
        format="json",
    )
    assert accepted.status_code == 201
    assert EventRegistration.objects.get(event=event).phone == "+15550199000"


def test_the_account_number_wins_over_a_supplied_one():
    """The supplied value is a fallback, not an override of the account's own record."""
    space = make_space()
    staff, attendee = manager(space), member(space)
    event = make_event(space)

    authed(staff).post(
        register_url(event),
        {"member_id": attendee.pk, "phone": "+15550000000"},
        format="json",
    )
    assert EventRegistration.objects.get(event=event).phone == "+15550100100"


def test_a_member_of_another_makerspace_is_refused():
    space = make_space()
    other = make_space("other-event-space")
    staff = manager(space)
    outsider = member(other, username="outsider")
    event = make_event(space)

    response = authed(staff).post(
        register_url(event), {"member_id": outsider.pk}, format="json"
    )
    assert response.status_code == 404
    assert not EventRegistration.objects.exists()


def test_the_roster_excludes_people_already_registered():
    space = make_space()
    staff = manager(space)
    signed_up = member(space, username="signed-up", display_name="Signed Up")
    free = member(space, username="free", display_name="Still Free")
    event = make_event(space)
    client = authed(staff)
    client.post(register_url(event), {"member_id": signed_up.pk}, format="json")

    rows = client.get(roster_url(event)).data
    ids = [row["member_id"] for row in rows]
    assert free.pk in ids
    assert signed_up.pk not in ids
    # A roster is not a contact export.
    assert set(rows[0]) == {"member_id", "display_name"}


def test_a_staffer_without_event_authority_reaches_neither_endpoint():
    space = make_space()
    attendee = member(space)
    event = make_event(space)
    plain = member(space, username="plain")

    assert authed(plain).get(roster_url(event)).status_code == 403
    assert authed(plain).post(
        register_url(event), {"member_id": attendee.pk}, format="json"
    ).status_code == 403


def test_the_events_module_gate_still_applies():
    from apps.makerspaces.module_install import uninstall_module

    space = make_space()
    staff, attendee = manager(space), member(space)
    event = make_event(space)
    uninstall_module(space, "events")

    assert authed(staff).post(
        register_url(event), {"member_id": attendee.pk}, format="json"
    ).status_code == 400
