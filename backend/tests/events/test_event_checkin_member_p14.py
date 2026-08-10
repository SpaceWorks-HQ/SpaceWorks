"""Phase 2 -- the member side of check-in: the token, and the QR that carries it.

Two rules do the work here. The token is surfaced only for a REGISTERED row, because a
waitlisted registration has nothing confirmable behind it and a QR that scans and then
fails is worse than no QR. And the QR route binds the ROUTE's makerspace before checking
ownership, so a registration cannot be pulled through an unrelated tenant's path.

The two status-only responses on the public registration endpoint -- the honeypot and the
duplicate branch -- must never leak a token, since both are deliberately indistinguishable
from a real registration.
"""

import pytest
from django.urls import reverse

from apps.events.models import EventRegistration
from apps.makerspaces import member_activity_service
from tests.events.checkin_helpers import (
    add_membership,
    client_for,
    make_event,
    make_member,
    make_space,
    register,
)

pytestmark = pytest.mark.django_db


def qr_url(space, registration):
    return reverse(
        "member-event-checkin-qr",
        kwargs={"makerspace_id": space.pk, "pk": registration.pk},
    )


def activity_rows(space, user):
    from apps.makerspaces.models import MakerspaceMembership

    membership = MakerspaceMembership.objects.get(makerspace=space, user=user)
    return member_activity_service.member_activity(membership)["event_registrations"]


# --- the token itself --------------------------------------------------------------


def test_every_registration_gets_a_distinct_token():
    space = make_space()
    event = make_event(space)
    tokens = {
        register(event, make_member(space, f"m{index}")).checkin_token
        for index in range(5)
    }

    assert len(tokens) == 5
    assert all(token is not None for token in tokens)


def test_the_token_survives_a_status_change():
    """A member's printed QR must not stop working because they were promoted."""
    space = make_space()
    event = make_event(space)
    registration = register(
        event, make_member(space), status=EventRegistration.Status.WAITLISTED
    )
    before = registration.checkin_token

    registration.status = EventRegistration.Status.REGISTERED
    registration.save(update_fields=["status"])
    registration.refresh_from_db()

    assert registration.checkin_token == before


# --- what the member is told -------------------------------------------------------


def test_member_activity_carries_the_token_for_a_registered_row():
    """A registration response alone is lost on reload, so it must be re-readable."""
    space = make_space()
    event = make_event(space)
    member = make_member(space)
    registration = register(event, member)

    row = next(r for r in activity_rows(space, member) if r["registration_id"] == registration.pk)

    assert row["checkin_token"] == str(registration.checkin_token)


def test_member_activity_withholds_the_token_from_a_waitlisted_row():
    space = make_space()
    event = make_event(space)
    member = make_member(space)
    registration = register(
        event, member, status=EventRegistration.Status.WAITLISTED
    )

    row = next(r for r in activity_rows(space, member) if r["registration_id"] == registration.pk)

    assert row["checkin_token"] is None


# --- the QR route ------------------------------------------------------------------


def test_a_member_can_render_their_own_qr():
    space = make_space()
    event = make_event(space)
    member = make_member(space)
    registration = register(event, member)

    response = client_for(member).get(qr_url(space, registration))

    assert response.status_code == 200
    assert response["Content-Type"] == "image/svg+xml"
    assert response["Cache-Control"] == "private, no-store"
    assert b"<svg" in response.content


def test_a_member_cannot_render_someone_elses_qr():
    space = make_space()
    event = make_event(space)
    theirs = register(event, make_member(space, "theirs"))

    response = client_for(make_member(space, "mine")).get(qr_url(space, theirs))

    assert response.status_code == 404


def test_a_registration_cannot_be_pulled_through_another_tenants_path():
    """Ownership alone is not enough -- the route's makerspace must bind the row too.

    The member here holds a real active membership in BOTH spaces, so the membership check
    passes and the only thing left to refuse the request is the makerspace binding on the
    lookup. An earlier version of this test used two different accounts and was therefore
    stopped by the membership check while appearing to prove the binding.
    """
    space, other = make_space("host"), make_space("elsewhere")
    member = make_member(space, "traveller")
    add_membership(other, member)
    registration = register(make_event(space), member)

    response = client_for(member).get(qr_url(other, registration))

    assert response.status_code in (403, 404)


def test_a_waitlisted_registration_has_no_qr():
    space = make_space()
    member = make_member(space)
    registration = register(
        make_event(space), member, status=EventRegistration.Status.WAITLISTED
    )

    assert client_for(member).get(qr_url(space, registration)).status_code == 404


def test_an_anonymous_caller_gets_no_qr():
    from rest_framework.test import APIClient

    space = make_space()
    registration = register(make_event(space), make_member(space))

    assert APIClient().get(qr_url(space, registration)).status_code in (401, 403)


# --- the two status-only responses must stay silent --------------------------------


def test_neither_the_honeypot_nor_the_duplicate_branch_leaks_a_token():
    """Both deliberately mimic a successful registration; a token would break the mimicry."""
    space = make_space()
    event = make_event(space)
    member = make_member(space)
    url = reverse(
        "public-event-register",
        kwargs={"makerspace_slug": space.slug, "public_token": event.public_token},
    )
    client = client_for(member)

    honeypot = client.post(url, {"website": "http://spam.test"}, format="json")
    client.post(url, {}, format="json")
    duplicate = client.post(url, {}, format="json")

    for response in (honeypot, duplicate):
        assert response.status_code == 201
        assert set(response.data) == {"status"}
        assert "checkin_token" not in str(response.data)


def test_a_cancelled_event_withdraws_the_qr_and_the_token():
    """Cancelling an EVENT leaves its registrations REGISTERED.

    `services.cancel()` changes only `Event.status`, so gating on the registration alone
    would keep handing the member an admission code for an event that is not happening --
    one `mark_attended` always refuses and the staff scanner is not even offered for.
    """
    from apps.events.models import Event

    space = make_space()
    event = make_event(space)
    member = make_member(space)
    registration = register(event, member)
    assert client_for(member).get(qr_url(space, registration)).status_code == 200

    event.status = Event.Status.CANCELLED
    event.save(update_fields=["status"])

    assert client_for(member).get(qr_url(space, registration)).status_code == 404
    row = next(r for r in activity_rows(space, member) if r["registration_id"] == registration.pk)
    assert row["checkin_token"] is None


def test_a_completed_event_still_allows_the_qr():
    """Staff routinely check people in after an event ends, so completed must stay usable."""
    from apps.events.models import Event

    space = make_space()
    event = make_event(space, status=Event.Status.COMPLETED)
    member = make_member(space)
    registration = register(event, member)

    assert client_for(member).get(qr_url(space, registration)).status_code == 200
    row = next(r for r in activity_rows(space, member) if r["registration_id"] == registration.pk)
    assert row["checkin_token"] == str(registration.checkin_token)
