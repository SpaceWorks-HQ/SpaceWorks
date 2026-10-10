"""events x membership state / money / module / edition: the untested cells (matrix E1, E3, E9, E13).

Each was right in the code with nothing pinning it, so a regression in any one would have
shipped silently.
"""

from django.core.cache import cache
from django.urls import reverse

import pytest

from apps.events.models import EventRegistration
from apps.makerspaces.models import MakerspaceMembership
from apps.payments.models import Payment
from tests.events.checkin_helpers import client_for, make_event, make_member, make_space, make_staff
from tests.events.checkin_helpers import register as add_registration

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def clear_throttles():
    cache.clear()
    yield
    cache.clear()


def _register_url(space, event):
    return reverse(
        "public-event-register",
        kwargs={"makerspace_slug": space.slug, "public_token": event.public_token},
    )


def test_a_revoked_member_cannot_register():
    """E1: a revoked membership is no membership, for registration as for borrowing."""
    space = make_space("combo-event-revoked")
    event = make_event(space)
    member = make_member(space)
    MakerspaceMembership.objects.filter(makerspace=space, user=member).update(status="revoked")

    response = client_for(member).post(_register_url(space, event), {}, format="json")

    assert response.status_code == 403, response.data
    assert not EventRegistration.objects.filter(event=event).exists()


def test_a_free_event_registers_without_recording_a_charge():
    """E3: `payment_amount = 0` records no debt even with charge tracking on."""
    space = make_space("combo-event-free")
    event = make_event(space, payment_amount=0)
    member = make_member(space)

    response = client_for(member).post(_register_url(space, event), {}, format="json")

    assert response.status_code == 201, response.data
    assert not Payment.objects.filter(makerspace=space).exists()


def test_a_pending_approval_registration_cannot_be_checked_in():
    """E9: only REGISTERED rows are check-in-able, so an unapproved applicant is refused."""
    space = make_space("combo-event-pending-checkin")
    event = make_event(space, registration_requires_approval=True)
    registration = add_registration(
        event, make_member(space), status=EventRegistration.Status.PENDING_APPROVAL
    )

    response = client_for(make_staff(space)).post(
        reverse("admin-event-registration-mark-attended", kwargs={"pk": registration.pk}),
        {},
        format="json",
    )

    assert response.status_code == 409, response.data
    registration.refresh_from_db()
    assert registration.status == EventRegistration.Status.PENDING_APPROVAL


def test_the_member_qr_route_refuses_with_events_uninstalled():
    """E13: the member's own check-in QR is an events surface and is gated like the rest."""
    space = make_space("combo-event-qr-off")
    member = make_member(space)
    registration = add_registration(make_event(space), member)
    space.enabled_modules = [key for key in space.enabled_modules if key != "events"]
    space.save(update_fields=["enabled_modules"])

    response = client_for(member).get(
        reverse("member-event-checkin-qr", kwargs={"makerspace_id": space.pk, "pk": registration.pk})
    )

    assert response.status_code == 400, response.data
    assert "events is disabled" in str(response.data)
