"""Phase 2 -- the staff-facing check-in resolve endpoint.

Resolve is read-only on purpose: it turns a scanned token into a name so the staffer can
see who is in front of them, and a separate confirm marks attendance. That split is both
what the owner asked for and the guard against confirming the wrong person's code.

The endpoint's whole risk surface is scoping. A token is a bearer value printed on a
member's phone, so the controls are: authorize the EVENT first, filter on event AND token
together, and answer unknown / malformed / wrong-event identically so the endpoint cannot
be used to tell those cases apart.
"""

from uuid import uuid4

import pytest
from django.core.cache import cache
from django.urls import resolve as resolve_url, reverse
from rest_framework.test import APIRequestFactory

from apps.events.models import EventRegistration
from apps.makerspaces import origin_scope
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


def resolve_endpoint(event):
    return reverse("admin-event-check-in-resolve", kwargs={"pk": event.pk})


def post_token(client, event, token):
    return client.post(
        resolve_endpoint(event), {"checkin_token": str(token)}, format="json"
    )


# --- the happy path ----------------------------------------------------------------


def test_a_scanned_token_resolves_to_the_registrant():
    space = make_space()
    event = make_event(space)
    member = make_member(space)
    registration = register(event, member)

    response = post_token(
        client_for(make_staff(space)), event, registration.checkin_token
    )

    assert response.status_code == 200
    assert response.data["registration_id"] == registration.pk
    assert response.data["name"] == member.display_name
    assert response.data["status"] == EventRegistration.Status.REGISTERED


def test_the_response_is_not_cacheable():
    """The body echoes a token-resolved identity, so it must not sit in a shared cache."""
    space = make_space()
    event = make_event(space)
    registration = register(event, make_member(space))

    response = post_token(
        client_for(make_staff(space)), event, registration.checkin_token
    )

    assert response["Cache-Control"] == "private, no-store"


def test_confirming_uses_the_existing_mark_attended_endpoint():
    """No new mutating token endpoint: confirm keeps its own pk-based authorization."""
    space = make_space()
    event = make_event(space)
    registration = register(event, make_member(space))
    client = client_for(make_staff(space))

    confirmed = client.post(
        reverse(
            "admin-event-registration-mark-attended", kwargs={"pk": registration.pk}
        ),
        {},
        format="json",
    )

    assert confirmed.status_code == 200
    registration.refresh_from_db()
    assert registration.status == EventRegistration.Status.ATTENDED


def test_a_second_confirm_is_a_conflict_not_a_double_count():
    space = make_space()
    event = make_event(space)
    registration = register(event, make_member(space))
    client = client_for(make_staff(space))
    url = reverse(
        "admin-event-registration-mark-attended", kwargs={"pk": registration.pk}
    )
    client.post(url, {}, format="json")

    again = client.post(url, {}, format="json")

    assert again.status_code == 409
    registration.refresh_from_db()
    assert registration.status == EventRegistration.Status.ATTENDED


# --- uniform not-found -------------------------------------------------------------


def test_unknown_malformed_and_wrong_event_tokens_are_indistinguishable():
    """Three different mistakes, one answer.

    Distinguishing them would turn the endpoint into an oracle: "this token is real but
    belongs elsewhere" is exactly the fact a stolen code should not be able to confirm.
    """
    space = make_space()
    event, other_event = make_event(space), make_event(space, "Other")
    elsewhere = register(other_event, make_member(space))
    client = client_for(make_staff(space))

    unknown = post_token(client, event, uuid4())
    malformed = client.post(
        resolve_endpoint(event), {"checkin_token": "not-a-uuid"}, format="json"
    )
    wrong_event = post_token(client, event, elsewhere.checkin_token)

    assert unknown.status_code == malformed.status_code == wrong_event.status_code == 404
    assert unknown.data == malformed.data == wrong_event.data


def test_a_waitlisted_registration_resolves_and_reports_its_status():
    """Resolving is not confirming: the host needs to see who this is and decide."""
    space = make_space()
    event = make_event(space)
    registration = register(
        event, make_member(space), status=EventRegistration.Status.WAITLISTED
    )

    response = post_token(
        client_for(make_staff(space)), event, registration.checkin_token
    )

    assert response.status_code == 200
    assert response.data["status"] == EventRegistration.Status.WAITLISTED


def test_a_waitlisted_registration_still_cannot_be_confirmed():
    space = make_space()
    event = make_event(space)
    registration = register(
        event, make_member(space), status=EventRegistration.Status.WAITLISTED
    )

    confirmed = client_for(make_staff(space)).post(
        reverse(
            "admin-event-registration-mark-attended", kwargs={"pk": registration.pk}
        ),
        {},
        format="json",
    )

    assert confirmed.status_code == 409


# --- authorization and tenancy -----------------------------------------------------


def test_staff_of_another_makerspace_cannot_resolve():
    space, other = make_space("host"), make_space("intruder")
    event = make_event(space)
    registration = register(event, make_member(space))

    response = post_token(
        client_for(make_staff(other)), event, registration.checkin_token
    )

    assert response.status_code in (403, 404)


def test_a_plain_member_cannot_resolve():
    space = make_space()
    event = make_event(space)
    registration = register(event, make_member(space))

    response = post_token(
        client_for(make_member(space, "nosy")), event, registration.checkin_token
    )

    assert response.status_code == 403


def test_the_route_is_event_scoped_for_origin_resolution():
    """The kwarg must be `pk`.

    `origin_scope_routes` resolves a MODEL_LOOKUPS entry by reading `kwargs['pk']` and
    marks the request invalid when it is absent, so a route declared `<int:event_id>`
    would be denied on every tenant custom domain despite being registered.
    """
    space = make_space()
    event = make_event(space)
    url = resolve_endpoint(event)
    match = resolve_url(url)
    request = APIRequestFactory().post(url)
    request.resolver_match = match
    view = match.func.view_class(**match.func.view_initkwargs)
    view.kwargs = match.kwargs

    assert "pk" in match.kwargs
    assert origin_scope._target_makerspace_id(request, view) == space.pk


def test_resolving_is_read_only():
    space = make_space()
    event = make_event(space)
    registration = register(event, make_member(space))

    post_token(client_for(make_staff(space)), event, registration.checkin_token)

    registration.refresh_from_db()
    assert registration.status == EventRegistration.Status.REGISTERED


# --- throttling --------------------------------------------------------------------


def test_repeated_resolution_is_throttled_per_staff_account():
    space = make_space()
    event = make_event(space)
    client = client_for(make_staff(space))

    statuses = {post_token(client, event, uuid4()).status_code for _ in range(80)}

    assert 429 in statuses


def test_a_cancelled_registration_resolves_but_reports_cancelled():
    """The staff UI gates confirm on `registered`, so this status must be reported plainly.

    A cancelled registration's QR still exists on the member's phone. Resolving it has to
    say so, because the alternative -- offering a confirm that `mark_attended` refuses --
    surfaced as a false "already checked in" at the door.
    """
    space = make_space()
    event = make_event(space)
    registration = register(
        event, make_member(space), status=EventRegistration.Status.CANCELLED
    )

    response = post_token(
        client_for(make_staff(space)), event, registration.checkin_token
    )

    assert response.status_code == 200
    assert response.data["status"] == EventRegistration.Status.CANCELLED


def test_a_cancelled_registration_cannot_be_confirmed():
    space = make_space()
    event = make_event(space)
    registration = register(
        event, make_member(space), status=EventRegistration.Status.CANCELLED
    )

    confirmed = client_for(make_staff(space)).post(
        reverse(
            "admin-event-registration-mark-attended", kwargs={"pk": registration.pk}
        ),
        {},
        format="json",
    )

    assert confirmed.status_code == 409
    registration.refresh_from_db()
    assert registration.status == EventRegistration.Status.CANCELLED
