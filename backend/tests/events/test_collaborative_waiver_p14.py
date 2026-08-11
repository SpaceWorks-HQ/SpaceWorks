"""Phase 3 -- a visiting member accepts the HOST's waiver, on the registration.

There is deliberately no membership at the host to hang this on: a visitor membership would
corrupt the host's member reporting, its roster, its quota and its dues, which is why the QR
scan is the admission record instead. So the acceptance lives on the registration, all-or-none
across three fields exactly as `MakerspaceMembership` constrains its own three.

The member's OWN space's waiver is separately enforced by `require_active_member`. This file is
about the other one -- the terms of the premises they are actually walking into.
"""

import pytest
from django.urls import reverse

from apps.events.models import EventRegistration
from apps.makerspaces.models import MakerspaceWaiver
from tests.events.collab_helpers import (
    client_for,
    collaborate,
    make_event,
    make_member,
    make_space,
)

pytestmark = pytest.mark.django_db


def register_url(space, event):
    return reverse(
        "member-collaborative-event-register",
        kwargs={"makerspace_id": space.pk, "pk": event.pk},
    )


def setup_pair(host_waiver_version=None):
    host, partner = make_space("host"), make_space("partner")
    event = make_event(host, is_public=False)
    collaborate(event, partner)
    member = make_member(partner, "visitor")
    waiver = None
    if host_waiver_version is not None:
        waiver = MakerspaceWaiver.objects.create(
            makerspace=host, is_active=True, version=host_waiver_version,
            body="Mind the laser.",
        )
    return host, partner, event, member, waiver


def test_the_hosts_waiver_is_shown_with_the_event():
    """A member cannot agree to terms they were never shown."""
    _, partner, event, member, waiver = setup_pair("v1")

    listed = client_for(member).get(
        reverse("member-collaborative-events", kwargs={"makerspace_id": partner.pk})
    )

    row = next(r for r in listed.data if r["id"] == event.pk)
    assert row["host_waiver"]["id"] == waiver.pk
    assert row["host_waiver"]["version"] == "v1"
    assert row["host_waiver"]["body"] == "Mind the laser."


def test_registration_is_refused_without_accepting_the_hosts_waiver():
    _, partner, event, member, _ = setup_pair("v1")

    response = client_for(member).post(register_url(partner, event), {}, format="json")

    assert response.status_code == 400
    assert "host_waiver" in response.data
    assert not EventRegistration.objects.filter(event=event).exists()


def test_accepting_the_current_waiver_records_all_three_fields_together():
    _, partner, event, member, waiver = setup_pair("v1")

    response = client_for(member).post(
        register_url(partner, event),
        {"host_waiver_id": waiver.pk, "host_waiver_version": "v1", "host_waiver_accepted": True},
        format="json",
    )

    assert response.status_code == 201
    registration = EventRegistration.objects.get(event=event, member=member)
    assert registration.host_waiver_id == waiver.pk
    assert registration.host_waiver_version_accepted == "v1"
    assert registration.host_waiver_accepted_at is not None


def test_a_superseded_version_is_not_acceptance():
    """Accepting terms that have since been replaced is not accepting the current terms."""
    host, partner, event, member, waiver = setup_pair("v1")
    waiver.is_active = False
    waiver.save(update_fields=["is_active"])
    current = MakerspaceWaiver.objects.create(
        makerspace=host, is_active=True, version="v2", body="Mind the laser, and the saw.",
    )

    response = client_for(member).post(
        register_url(partner, event),
        {"host_waiver_id": waiver.pk, "host_waiver_version": "v1", "host_waiver_accepted": True},
        format="json",
    )

    assert response.status_code == 400
    assert not EventRegistration.objects.filter(event=event).exists()
    assert current.version == "v2"


def test_a_mismatched_version_for_the_right_waiver_is_refused():
    _, partner, event, member, waiver = setup_pair("v1")

    response = client_for(member).post(
        register_url(partner, event),
        {"host_waiver_id": waiver.pk, "host_waiver_version": "v99"},
        format="json",
    )

    assert response.status_code == 400


def test_a_host_without_a_waiver_requires_and_stores_nothing():
    _, partner, event, member, _ = setup_pair()

    response = client_for(member).post(register_url(partner, event), {}, format="json")

    assert response.status_code == 201
    registration = EventRegistration.objects.get(event=event, member=member)
    assert registration.host_waiver_id is None
    assert registration.host_waiver_accepted_at is None
    assert registration.host_waiver_version_accepted is None


def test_a_hosts_own_member_is_not_asked_twice():
    """Their membership already carries the acceptance via require_active_member."""
    from apps.makerspaces.waiver_services import accept_waiver
    from apps.makerspaces.models import MakerspaceMembership

    host, partner, event, _, _ = setup_pair("v1")
    own = make_member(host, "insider")
    accept_waiver(MakerspaceMembership.objects.get(makerspace=host, user=own))

    response = client_for(own).post(register_url(host, event), {}, format="json")

    assert response.status_code == 201
    registration = EventRegistration.objects.get(event=event, member=own)
    assert registration.host_waiver_id is None


def test_the_acceptance_fields_are_all_or_none():
    """One partial write would make the stored evidence unreadable."""
    from django.db.utils import IntegrityError

    _, partner, event, member, waiver = setup_pair("v1")
    client_for(member).post(
        register_url(partner, event),
        {"host_waiver_id": waiver.pk, "host_waiver_version": "v1", "host_waiver_accepted": True},
        format="json",
    )
    registration = EventRegistration.objects.get(event=event, member=member)

    with pytest.raises(IntegrityError):
        EventRegistration.objects.filter(pk=registration.pk).update(
            host_waiver_version_accepted=None
        )
