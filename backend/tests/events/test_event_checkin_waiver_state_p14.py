"""What the scanner is told about waiver evidence and confirmability.

This contract had NO test before -- the endpoint reported `bool(registration.host_waiver_id)`
and nothing asserted on it, which is how it shipped structurally false for every host member.
A host member's acceptance lives on their `MakerspaceMembership`; only a VISITOR's is stamped
on the registration, because `views_member_events` deliberately does not re-record an
agreement the member already gave to their own space.

Everything here is reported, never enforced: the endpoint hands the staffer facts and the
door stays open. `confirmable` exists so the UI stops offering a button whose request can
only 409 -- it mirrors `mark_attended`'s own precondition rather than inventing a second one.
"""

import pytest
from django.core.cache import cache
from django.urls import reverse

from apps.events.models import Event, EventRegistration
from apps.makerspaces.models import MakerspaceWaiver
from tests.events.checkin_helpers import (
    client_for,
    make_event,
    make_member,
    make_space,
    make_staff,
    register,
)

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def clear_throttles():
    cache.clear()
    yield
    cache.clear()


def waiver(space, version="v1", active=True):
    return MakerspaceWaiver.objects.create(
        makerspace=space, body="Mind the laser.", version=version, is_active=active,
    )


def accept_on_membership(space, user, wv):
    from django.utils import timezone
    from apps.makerspaces.models import MakerspaceMembership

    MakerspaceMembership.objects.filter(makerspace=space, user=user).update(
        accepted_waiver=wv,
        waiver_accepted_at=timezone.now(),
        waiver_version_accepted=wv.version,
    )


def resolve(space, event, registration):
    client = client_for(make_staff(space))
    return client.post(
        reverse("admin-event-check-in-resolve", kwargs={"pk": event.pk}),
        {"checkin_token": str(registration.checkin_token)},
        format="json",
    )


# --- waiver evidence ---------------------------------------------------------------


def test_a_host_with_no_active_waiver_requires_nothing():
    space = make_space()
    event = make_event(space)
    member = make_member(space)

    response = resolve(space, event, register(event, member))

    assert response.data["host_waiver_state"] == "not_required"


def test_a_host_member_who_accepted_on_their_membership_is_on_file():
    """The regression. This member accepted properly and was told to take one at the desk."""
    space = make_space()
    wv = waiver(space)
    event = make_event(space)
    member = make_member(space)
    accept_on_membership(space, member, wv)

    response = resolve(space, event, register(event, member))

    assert response.data["host_waiver_state"] == "on_file"


def test_a_staff_created_host_registration_without_acceptance_is_missing():
    """Staff registration only requires a membership to EXIST -- never an acceptance.

    So a host member really can stand at the door with nothing on file, and reading
    "not a visitor" as "not required" would hide exactly that case.
    """
    space = make_space()
    waiver(space)
    event = make_event(space)
    member = make_member(space)

    response = resolve(space, event, register(event, member))

    assert response.data["host_waiver_state"] == "missing"


def test_a_superseded_acceptance_still_counts():
    """A host revising its terms must not strand someone who already agreed."""
    space = make_space()
    old = waiver(space, version="v1", active=False)
    waiver(space, version="v2")
    event = make_event(space)
    member = make_member(space)
    accept_on_membership(space, member, old)

    response = resolve(space, event, register(event, member))

    assert response.data["host_waiver_state"] == "on_file"


def test_a_registration_stamped_acceptance_is_on_file():
    space = make_space()
    wv = waiver(space)
    event = make_event(space)
    member = make_member(space)
    registration = register(event, member)
    EventRegistration.objects.filter(pk=registration.pk).update(
        host_waiver=wv, host_waiver_version_accepted=wv.version,
        host_waiver_accepted_at="2026-01-01T00:00:00Z",
    )

    response = resolve(space, event, registration)

    assert response.data["host_waiver_state"] == "on_file"


def test_a_registration_with_no_member_falls_back_to_missing():
    """A walk-in row carries no account, so there is no membership to consult."""
    space = make_space()
    waiver(space)
    event = make_event(space)

    response = resolve(space, event, register(event, None))

    assert response.data["host_waiver_state"] == "missing"


# --- confirmability ----------------------------------------------------------------


@pytest.mark.parametrize(
    "status,expected",
    [
        (EventRegistration.Status.REGISTERED, True),
        (EventRegistration.Status.WAITLISTED, False),
        (EventRegistration.Status.CANCELLED, False),
        (EventRegistration.Status.ATTENDED, False),
    ],
)
def test_only_a_registered_row_is_confirmable(status, expected):
    space = make_space()
    event = make_event(space)
    member = make_member(space)

    response = resolve(space, event, register(event, member, status=status))

    assert response.data["confirmable"] is expected


def test_a_registered_row_on_a_cancelled_event_is_not_confirmable():
    """mark_attended refuses it, so offering the button could only ever produce a 409."""
    space = make_space()
    event = make_event(space)
    member = make_member(space)
    registration = register(event, member)
    Event.objects.filter(pk=event.pk).update(status=Event.Status.CANCELLED)

    response = resolve(space, event, registration)

    assert response.data["confirmable"] is False
    assert response.data["event_status"] == "cancelled"


def test_a_completed_event_still_confirms():
    """Checking someone in after the event ended is normal; only cancellation is not."""
    space = make_space()
    event = make_event(space)
    member = make_member(space)
    registration = register(event, member)
    Event.objects.filter(pk=event.pk).update(status=Event.Status.COMPLETED)

    response = resolve(space, event, registration)

    assert response.data["confirmable"] is True
