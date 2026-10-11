import pytest
from django.urls import reverse

from apps.accounts import rbac
from apps.events.models import EventOrganizer
from apps.events.invites import create_invite
from apps.events.promos import create_promo
from apps.events.ticketing import create_ticket
from apps.organizations.models import Organization, OrganizationMembership
from tests.events.collab_helpers import client_for, make_staff, make_member, collaborate
from tests.events.ticketing_helpers import account, event_space, open_event

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("kind", ["invite", "promo"])
def test_organization_event_manager_can_revoke_only_its_own_event_codes(kind):
    space = event_space()
    event, other = open_event(space), open_event(space)
    organizer = account("organizer")
    org = Organization.objects.create(name="Organizers", slug="organizers")
    OrganizationMembership.objects.create(organization=org, user=organizer, granted_actions=[rbac.Action.MANAGE_EVENTS])
    EventOrganizer.objects.create(event=event, organization=org)
    list_route, revoke_route, data = ("admin-event-invites", "admin-event-invite-revoke", {}) if kind == "invite" else ("admin-event-promos", "admin-event-promo-revoke", {"percent_off": 20})
    client = client_for(organizer)
    created = client.post(reverse(list_route, args=[event.pk]), data, format="json")
    assert created.status_code == 201, created.data
    assert client.get(reverse(list_route, args=[event.pk])).status_code == 200
    assert client.post(reverse(revoke_route, args=[created.data["id"]]), {}, format="json").status_code == 200
    create = create_invite if kind == "invite" else create_promo
    foreign, _ = create(other, actor=make_staff(space), **data)
    assert client.post(reverse(revoke_route, args=[foreign.pk]), {}, format="json").status_code == 404


def test_collaborative_discovery_exposes_eligible_tickets_and_registration_uses_codes():
    host, partner = event_space("host", membership=True), event_space("partner", membership=True)
    event = open_event(host, "invite")
    event.is_public = False
    event.save(update_fields=["is_public"])
    collaborate(event, partner)
    visitor = make_member(partner)
    staff = make_staff(host)
    invite, code = create_invite(event, actor=staff, email=visitor.email)
    ticket = create_ticket(event, actor=staff, name="Public", amount=10)
    create_ticket(event, actor=staff, name="Host members", amount=5, audience="member")
    promo, promo_code = create_promo(event, actor=staff, percent_off=50)
    client = client_for(visitor)
    listed = client.get(reverse("member-collaborative-events", args=[partner.pk]))
    assert listed.status_code == 200
    row = next(row for row in listed.data if row["id"] == event.pk)
    assert row["registration_audience"] == "invite" and row["promo_codes_enabled"] is True
    assert [item["id"] for item in row["ticket_types"]] == [ticket.pk]
    response = client.post(reverse("member-collaborative-event-register", args=[partner.pk, event.pk]), {"ticket_type_id": ticket.pk, "invite_code": code, "promo_code": promo_code}, format="json")
    assert response.status_code == 201, response.data
    assert event.registrations.get(member=visitor).quoted_amount == 5
