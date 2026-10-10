from datetime import timedelta

import pytest
from django.utils import timezone

from apps.accounts import rbac
from apps.bookings.models import BookableSpace, Booking
from apps.events.models import Event
from apps.hardware_requests.models import HardwareRequest
from apps.makerspaces.models import MakerspaceMembership, MakerspaceRole
from tests.module_helpers import disable_module
from tests.return_helpers import authenticated_client, make_member, make_product, make_space, make_user

pytestmark = pytest.mark.django_db


def url(space, q="laser", limit=5):
    return f"/api/v1/admin/search?makerspace_id={space.pk}&q={q}&limit={limit}"


def actor_with(space, name, actions):
    actor = make_user(name, access_status="active")
    role = MakerspaceRole.objects.create(makerspace=space, name=name, slug=name, granted_actions=actions)
    MakerspaceMembership.objects.create(makerspace=space, user=actor, role="custom", assigned_role=role)
    return actor


def seed(space, suffix):
    manager = make_member(f"laser-{suffix}", space)
    product = make_product(space, "laser cutter")
    request = HardwareRequest.objects.create(makerspace=space, requester=manager, requester_name="Laser borrower", requested_for="laser work", status="pending_approval")
    now = timezone.now()
    event = Event.objects.create(makerspace=space, title="Laser workshop", starts_at=now, ends_at=now + timedelta(hours=1))
    room = BookableSpace.objects.create(makerspace=space, name="Laser room")
    booking = Booking.objects.create(space=room, name="Private Person", email="private@example.test", starts_at=now, ends_at=now + timedelta(hours=1))
    return manager, {"inventory": product.pk, "requests": request.pk, "events": event.pk, "bookings": booking.pk,
                     "members": manager.makerspace_memberships.get(makerspace=space).pk}


def test_search_is_tenant_scoped_and_returns_only_typed_minimal_hits():
    space, foreign = make_space("search-local"), make_space("search-foreign")
    manager, expected = seed(space, "local")
    _other_manager, foreign_ids = seed(foreign, "foreign")
    client = authenticated_client(manager)
    response = client.get(url(space))
    assert response.status_code == 200, response.data
    for entity, pk in expected.items():
        assert any(hit["entity"] == entity and hit["id"] == pk for hit in response.data["results"])
        assert not any(hit["entity"] == entity and hit["id"] == foreign_ids[entity] for hit in response.data["results"])
    assert all(set(hit) == {"entity", "id", "label", "tab", "query"} for hit in response.data["results"])
    assert "private@example.test" not in str(response.data)
    for hit in response.data["results"]:
        if hit["entity"] in {"inventory", "members", "requests"}:
            assert hit["query"]["id"] == str(hit["id"])
    assert client.get(url(foreign)).status_code == 404


def test_inventory_only_staff_cannot_discover_members_requests_or_events():
    space = make_space("search-actions")
    seed(space, "actions")
    actor = actor_with(space, "search-inventory", [rbac.Action.VIEW_INVENTORY])
    response = authenticated_client(actor).get(url(space))
    assert response.status_code == 200
    assert {hit["entity"] for hit in response.data["results"]} == {"inventory"}


def test_handover_staff_never_see_pending_or_draft_requests():
    space = make_space("search-handover")
    manager, _ = seed(space, "handover")
    accepted = HardwareRequest.objects.create(makerspace=space, requester=manager, requested_for="laser", status="accepted")
    HardwareRequest.objects.create(makerspace=space, requester=manager, requested_for="laser", status="draft")
    actor = actor_with(space, "search-handout", [rbac.Action.ISSUE_REQUEST])
    response = authenticated_client(actor).get(url(space))
    assert [hit["id"] for hit in response.data["results"] if hit["entity"] == "requests"] == [accepted.pk]


def test_search_limits_each_entity_and_omits_disabled_modules():
    space = make_space("search-bounds")
    manager = make_member("search-bounds-manager", space)
    for n in range(12):
        make_product(space, f"laser tool {n}")
    client = authenticated_client(manager)
    response = client.get(url(space, limit=2))
    assert len([hit for hit in response.data["results"] if hit["entity"] == "inventory"]) == 2
    disable_module(space, "staff_admin")
    assert not any(hit["entity"] == "inventory" for hit in client.get(url(space)).data["results"])


@pytest.mark.parametrize("query", ["q=x", "q=" + "x" * 101, "q=laser&limit=11", "q=laser&limit=0", "q=laser&makerspace_id=bad"])
def test_search_validates_inputs(query):
    space = make_space("search-input")
    manager = make_member("search-input-manager", space)
    assert authenticated_client(manager).get(f"/api/v1/admin/search?makerspace_id={space.pk}&{query}").status_code == 400


def test_search_is_throttled():
    space = make_space("search-throttle")
    manager = make_member("search-throttle-manager", space)
    client = authenticated_client(manager)
    for _ in range(60):
        assert client.get(url(space)).status_code == 200
    assert client.get(url(space)).status_code == 429


def test_large_numeric_search_cannot_overflow_booking_primary_keys():
    space = make_space("search-big-id")
    manager = make_member("search-big-id-manager", space)
    response = authenticated_client(manager).get(url(space, q="9" * 100))
    assert response.status_code == 200
    assert response.data["results"] == []


def test_suspended_actor_cannot_search_or_access_saved_views():
    space = make_space("search-suspended")
    manager = make_member("search-suspended-manager", space)
    manager.access_status = "suspended"
    manager.save(update_fields=["access_status"])
    client = authenticated_client(manager)
    assert client.get(url(space)).status_code == 403
    assert client.get(f"/api/v1/admin/makerspaces/{space.pk}/saved-views?entity=inventory").status_code == 403


def test_machine_search_obeys_role_machine_scope():
    from apps.machines.models import Machine, MachineType, RoleMachineScope

    space = make_space("search-machines")
    machine_type = MachineType.objects.create(makerspace=space, name="Laser", slug="laser")
    visible = Machine.objects.create(makerspace=space, machine_type=machine_type, name="Laser permitted")
    hidden = Machine.objects.create(makerspace=space, machine_type=machine_type, name="Laser hidden")
    actor = actor_with(space, "search-machines-actor", [rbac.Action.MANAGE_MACHINES])
    membership = actor.makerspace_memberships.get(makerspace=space)
    RoleMachineScope.objects.create(role=membership.assigned_role, machine=visible)
    response = authenticated_client(actor).get(url(space))
    ids = [hit["id"] for hit in response.data["results"] if hit["entity"] == "machines"]
    assert ids == [visible.pk] and hidden.pk not in ids


def test_tenant_browser_origin_cannot_search_a_second_authorized_tenant():
    space, foreign = make_space("search-origin"), make_space("search-origin-other")
    space.frontend_domain = "search-origin.example.test"
    space.frontend_domain_status = "verified"
    space.save(update_fields=["frontend_domain", "frontend_domain_status"])
    manager = make_member("search-origin-manager", space)
    MakerspaceMembership.objects.create(makerspace=foreign, user=manager, role="space_manager")
    client = authenticated_client(manager)
    assert client.get(url(foreign), HTTP_ORIGIN="https://search-origin.example.test").status_code == 403
    assert client.get(f"/api/v1/admin/makerspaces/{foreign.pk}/saved-views?entity=inventory", HTTP_ORIGIN="https://search-origin.example.test").status_code == 403


def test_encrypted_search_candidates_are_intersected_with_request_scope(settings, monkeypatch):
    from apps.encryption import search

    space, foreign = make_space("search-indexed"), make_space("search-indexed-foreign")
    manager, local = seed(space, "indexed")
    _foreign_manager, other = seed(foreign, "indexed-other")
    settings.PII_ENCRYPTION_ENABLED = True
    settings.PII_ENCRYPTION_DUAL_READ = False
    monkeypatch.setattr(search, "indexed_candidates", lambda **kwargs: [local["requests"], other["requests"]])

    def scoped_ids(rows, **kwargs):
        ids = list(rows.values_list("pk", flat=True))
        assert other["requests"] not in ids
        return ids

    monkeypatch.setattr(search, "verified_ids", scoped_ids)
    response = authenticated_client(manager).get(url(space, q="indexedmatch"))
    assert response.status_code == 200, response.data
    assert [hit["id"] for hit in response.data["results"] if hit["entity"] == "requests"] == [local["requests"]]


def test_organization_action_grants_reach_search_without_widening_entity_authority():
    from apps.organizations.models import Organization, OrganizationMakerspace, OrganizationMembership

    space, foreign = make_space("search-org"), make_space("search-org-other")
    seed(space, "org")
    seed(foreign, "org-other")
    actor = make_user("search-org-actor", access_status="active")
    org = Organization.objects.create(name="Search organization", slug="search-organization")
    OrganizationMakerspace.objects.create(organization=org, makerspace=space, relationship="manager")
    OrganizationMembership.objects.create(organization=org, user=actor, granted_actions=[rbac.Action.VIEW_INVENTORY])
    client = authenticated_client(actor)
    response = client.get(url(space))
    assert response.status_code == 200, response.data
    assert {hit["entity"] for hit in response.data["results"]} == {"inventory"}
    assert client.get(url(foreign)).status_code == 404
    views = f"/api/v1/admin/makerspaces/{space.pk}/saved-views"
    created = client.post(views, {"name": "Org tools", "entity": "inventory", "state": {"q": "laser"}}, format="json")
    assert created.status_code == 201, created.data
    assert client.get(views + "?entity=inventory").data["count"] == 1
    assert client.post(views, {"name": "Money", "entity": "payments", "state": {}}, format="json").status_code == 403


def test_hidden_and_archived_tenants_are_refused_even_for_a_global_superadmin():
    from apps.accounts.models import User

    hidden, archived = make_space("search-hidden"), make_space("search-archived")
    seed(hidden, "hidden")
    seed(archived, "archived")
    hidden.superadmin_access_enabled = False
    hidden.save(update_fields=["superadmin_access_enabled"])
    archived.archived_at = timezone.now()
    archived.save(update_fields=["archived_at"])
    actor = make_user("search-global-admin", role=User.Role.SUPERADMIN, access_status="active")
    client = authenticated_client(actor)
    for space in (hidden, archived):
        assert client.get(url(space)).status_code == 404
        assert client.get(f"/api/v1/admin/makerspaces/{space.pk}/saved-views?entity=inventory").status_code == 404


@pytest.mark.parametrize("module,entity", [("request_workflow", "requests"), ("bookings", "bookings"), ("events", "events")])
def test_search_does_not_discover_an_entity_when_its_module_is_off(module, entity):
    space = make_space("search-module-" + module)
    manager, _expected = seed(space, "module-" + module)
    client = authenticated_client(manager)
    before = client.get(url(space))
    assert before.status_code == 200 and any(hit["entity"] == entity for hit in before.data["results"])
    disable_module(space, module)
    after = client.get(url(space))
    assert after.status_code == 200 and not any(hit["entity"] == entity for hit in after.data["results"])
