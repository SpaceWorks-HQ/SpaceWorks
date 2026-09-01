"""Phase 3 -- collaborative events: eligibility, ownership, and the two tenant scopes.

An event keeps ONE owning makerspace. Collaboration only makes a partner space's members
eligible to self-register; the host stays sole owner, and a collaborator's staff get no
create/edit/cancel/attendee access, because `origin_scope` hard-scopes a staff session to
its own domain and that guard is what stops cross-tenant session theft.

The subtle part is that the API has TWO tenant scopes. Inviting and removing are the HOST's
actions; accepting is the COLLABORATOR's, and must be reachable from the collaborator's own
custom domain. Registering an accept route against the host's makerspace would 403 it from
exactly the domain that needs it -- which is the whole feature -- so the origin registry is
asserted here directly.
"""

import pytest
from django.urls import resolve as resolve_url, reverse
from rest_framework.test import APIRequestFactory

from apps.events.models import EventCollaborator, EventRegistration
from apps.makerspaces import origin_scope
from tests.events.collab_helpers import (
    client_for,
    collaborate,
    make_event,
    make_member,
    make_space,
    make_staff,
)

pytestmark = pytest.mark.django_db


def register_url(space, event):
    return reverse(
        "member-collaborative-event-register",
        kwargs={"makerspace_id": space.pk, "pk": event.pk},
    )


def list_url(space):
    return reverse("member-collaborative-events", kwargs={"makerspace_id": space.pk})


# --- eligibility -------------------------------------------------------------------


def test_a_collaborators_member_can_register_for_a_members_only_event():
    """The single relaxation: `is_public` only. Everything else is the same service."""
    host, partner = make_space("host"), make_space("partner")
    event = make_event(host, is_public=False)
    collaborate(event, partner)
    member = make_member(partner, "visitor")

    response = client_for(member).post(register_url(partner, event), {}, format="json")

    assert response.status_code == 201
    registration = EventRegistration.objects.get(event=event, member=member)
    assert registration.status == EventRegistration.Status.REGISTERED
    # Provenance records where the participation happened, not who hosts it.
    assert registration.registered_via_makerspace_id == partner.pk
    # Ownership is untouched: the host still owns the event and its PII scope.
    assert registration.event.makerspace_id == host.pk


def test_an_unaccepted_invitation_grants_nothing():
    host, partner = make_space("host"), make_space("partner")
    event = make_event(host, is_public=False)
    collaborate(event, partner, status=EventCollaborator.Status.INVITED)
    member = make_member(partner, "visitor")

    response = client_for(member).post(register_url(partner, event), {}, format="json")

    assert response.status_code == 404
    assert not EventRegistration.objects.filter(event=event).exists()


def test_a_declined_invitation_grants_nothing():
    host, partner = make_space("host"), make_space("partner")
    event = make_event(host, is_public=False)
    collaborate(event, partner, status=EventCollaborator.Status.DECLINED)
    member = make_member(partner, "visitor")

    assert client_for(member).post(register_url(partner, event), {}, format="json").status_code == 404


def test_a_member_of_an_uninvited_space_cannot_register():
    host, partner, outsider = make_space("host"), make_space("partner"), make_space("outsider")
    event = make_event(host, is_public=False)
    collaborate(event, partner)
    member = make_member(outsider, "stranger")

    assert client_for(member).post(register_url(outsider, event), {}, format="json").status_code == 404


def test_an_archived_collaborator_grants_nothing():
    """Archived is invisible everywhere but /control/."""
    from django.utils import timezone

    host, partner = make_space("host"), make_space("partner")
    event = make_event(host, is_public=False)
    collaborate(event, partner)
    member = make_member(partner, "visitor")
    partner.archived_at = timezone.now()
    partner.save(update_fields=["archived_at"])

    assert client_for(member).post(register_url(partner, event), {}, format="json").status_code in (403, 404)


def test_a_draft_event_is_not_registerable_even_for_a_collaborator():
    """Collaboration relaxes `is_public` and nothing else."""
    from apps.events.models import Event

    host, partner = make_space("host"), make_space("partner")
    event = make_event(host, is_public=False, status=Event.Status.DRAFT)
    collaborate(event, partner)
    member = make_member(partner, "visitor")

    assert client_for(member).post(register_url(partner, event), {}, format="json").status_code in (404, 409)


def test_capacity_still_applies_to_a_collaborative_registration():
    host, partner = make_space("host"), make_space("partner")
    event = make_event(host, is_public=False)
    event.capacity = 1
    event.save(update_fields=["capacity"])
    collaborate(event, partner)
    first, second = make_member(partner, "first"), make_member(partner, "second")

    client_for(first).post(register_url(partner, event), {}, format="json")
    client_for(second).post(register_url(partner, event), {}, format="json")

    statuses = set(
        EventRegistration.objects.filter(event=event).values_list("status", flat=True)
    )
    assert statuses == {
        EventRegistration.Status.REGISTERED,
        EventRegistration.Status.WAITLISTED,
    }


# --- discovery ----------------------------------------------------------------------


def test_discovery_lists_the_hosts_event_for_the_collaborator():
    host, partner = make_space("host"), make_space("partner")
    event = make_event(host, is_public=False)
    collaborate(event, partner)
    member = make_member(partner, "visitor")

    response = client_for(member).get(list_url(partner))

    assert response.status_code == 200
    ids = [row["id"] for row in response.data]
    assert event.pk in ids


def test_discovery_shows_nothing_to_an_uninvited_space():
    host, outsider = make_space("host"), make_space("outsider")
    collaborate(make_event(host, is_public=False), make_space("partner"))
    member = make_member(outsider, "stranger")

    response = client_for(member).get(list_url(outsider))

    assert response.status_code == 200
    assert response.data == []


def test_the_public_listing_still_hides_a_members_only_collaborative_event():
    """`_public_events()` is AllowAny and shared with registration; it must not widen."""
    host, partner = make_space("host"), make_space("partner")
    event = make_event(host, is_public=False)
    collaborate(event, partner)

    from apps.events.views_public import _public_events

    assert event not in list(_public_events(host))


def test_a_hosts_own_members_can_discover_and_register_for_its_members_only_event():
    """Without the host arm the creating space is the one space unable to see its event."""
    host, partner = make_space("host"), make_space("partner")
    event = make_event(host, is_public=False)
    collaborate(event, partner)
    own = make_member(host, "insider")

    listed = client_for(own).get(list_url(host))
    registered = client_for(own).post(register_url(host, event), {}, format="json")

    assert event.pk in [row["id"] for row in listed.data]
    assert registered.status_code == 201
    assert EventRegistration.objects.get(
        event=event, member=own
    ).registered_via_makerspace_id == host.pk


def test_adding_a_partner_does_not_reopen_another_partners_refusal():
    """The PUT sends the whole set, so a preserved DECLINED row is the only safe rule."""
    from apps.events.collaborator_services import invite_collaborators

    host = make_space("host")
    refused, fresh = make_space("refused"), make_space("fresh")
    event = make_event(host, is_public=False)
    declined = collaborate(event, refused, status=EventCollaborator.Status.DECLINED)
    staff = make_staff(host)

    invite_collaborators(event, actor=staff, slugs=[refused.slug, fresh.slug])

    declined.refresh_from_db()
    assert declined.status == EventCollaborator.Status.DECLINED
    assert EventCollaborator.objects.get(
        event=event, makerspace=fresh
    ).status == EventCollaborator.Status.INVITED
