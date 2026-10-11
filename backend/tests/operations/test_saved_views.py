"""Personal ownership and tenant-sharing are separate from list authority."""
import pytest

from apps.accounts import rbac
from apps.audit.models import AuditLog
from apps.makerspaces.models import MakerspaceMembership, MakerspaceRole
from apps.operations.models import SavedView
from tests.module_helpers import disable_module
from tests.return_helpers import authenticated_client, make_member, make_space, make_user

pytestmark = pytest.mark.django_db


def url(space, pk=None):
    base = f"/api/v1/admin/makerspaces/{space.pk}/saved-views"
    return f"{base}/{pk}" if pk else base


def inventory_reader(space, name):
    actor = make_user(name, access_status="active")
    role = MakerspaceRole.objects.create(makerspace=space, name=name, slug=name, granted_actions=[rbac.Action.VIEW_INVENTORY])
    MakerspaceMembership.objects.create(makerspace=space, user=actor, role="custom", assigned_role=role)
    return actor


def payload(**extra):
    return {"name": "Low stock", "entity": "inventory", "state": {"q": "drill", "low_stock": "true", "ordering": "name"}, **extra}


def test_private_views_follow_owner_and_refuse_other_tenants():
    space, other = make_space("saved-own"), make_space("saved-foreign")
    owner = inventory_reader(space, "saved-owner")
    peer = inventory_reader(space, "saved-peer")
    client = authenticated_client(owner)
    created = client.post(url(space), payload(), format="json")
    assert created.status_code == 201, created.data
    pk = created.data["id"]
    assert created.data["owner"] == owner.pk and created.data["shared"] is False
    assert client.get(url(space) + "?entity=inventory").data["results"][0]["id"] == pk
    peer_client = authenticated_client(peer)
    assert peer_client.get(url(space) + "?entity=inventory").data["results"] == []
    assert peer_client.get(url(space, pk)).status_code == 404
    assert peer_client.patch(url(space, pk), {"name": "Steal"}, format="json").status_code == 404
    assert client.post(url(other), payload(), format="json").status_code == 404
    assert client.get(url(other, pk)).status_code == 404
    assert client.delete(url(other, pk)).status_code == 404
    assert AuditLog.objects.filter(actor=owner, action="saved_view.created", target_id=str(pk)).exists()


def test_only_managers_share_and_peers_cannot_change_shared_views():
    space = make_space("saved-share")
    manager = make_member("saved-manager", space)
    reader = inventory_reader(space, "saved-reader")
    client = authenticated_client(manager)
    denied = authenticated_client(reader).post(url(space), payload(shared=True), format="json")
    assert denied.status_code == 403
    created = client.post(url(space), payload(shared=True), format="json")
    assert created.status_code == 201, created.data
    pk = created.data["id"]
    peer_client = authenticated_client(reader)
    assert peer_client.get(url(space) + "?entity=inventory").data["results"][0]["id"] == pk
    assert peer_client.patch(url(space, pk), {"shared": False}, format="json").status_code == 403
    assert peer_client.delete(url(space, pk)).status_code == 403
    assert AuditLog.objects.filter(actor=manager, action="saved_view.shared", target_id=str(pk)).exists()
    assert client.patch(url(space, pk), {"shared": False}, format="json").status_code == 200
    assert peer_client.get(url(space, pk)).status_code == 404
    assert AuditLog.objects.filter(action="saved_view.unshared", target_id=str(pk)).exists()


def test_shared_view_never_grants_access_to_an_entity_and_module_off_is_400():
    space = make_space("saved-authority")
    manager = make_member("saved-authority-manager", space)
    reader = inventory_reader(space, "saved-authority-reader")
    row = SavedView.objects.create(makerspace=space, owner=manager, name="Money", entity="payments", shared=True)
    client = authenticated_client(reader)
    assert client.get(url(space, row.pk)).status_code == 403
    assert client.get(url(space) + "?entity=payments").status_code == 403
    disable_module(space, "events")
    assert authenticated_client(manager).get(url(space) + "?entity=events").status_code == 400


@pytest.mark.parametrize("state", [{"url": "https://evil.test"}, {"q": "x" * 251}, {"q": {"nested": True}}])
def test_saved_state_is_bounded_and_inert(state):
    space = make_space("saved-validate")
    manager = make_member("saved-validate-manager", space)
    assert authenticated_client(manager).post(url(space), payload(state=state), format="json").status_code == 400
    assert SavedView.objects.count() == 0


def test_deleted_view_is_audited_and_list_is_paginated():
    space = make_space("saved-pages")
    owner = make_member("saved-pages-owner", space)
    SavedView.objects.bulk_create([SavedView(makerspace=space, owner=owner, entity="inventory", name=f"View {n:02d}") for n in range(25)])
    client = authenticated_client(owner)
    page = client.get(url(space) + "?entity=inventory")
    assert page.data["count"] == 25 and len(page.data["results"]) == 24
    pk = page.data["results"][0]["id"]
    assert client.delete(url(space, pk)).status_code == 204
    assert AuditLog.objects.filter(action="saved_view.deleted", target_id=str(pk)).exists()


def test_import_projection_clears_source_publication_and_identity_filters():
    from apps.data_export.guards import validate_semantic_references, validate_user_edges
    from apps.tenant_migration.tenant_dump_catalog import validate_catalog
    from apps.tenant_migration.target_projection import TARGET_FIELD_PROJECTION

    validate_catalog()
    validate_user_edges()
    validate_semantic_references()
    assert TARGET_FIELD_PROJECTION[("operations.SavedView", "shared")].resolved_value("operations.SavedView", "shared") is False
    assert TARGET_FIELD_PROJECTION[("operations.SavedView", "state")].resolved_value("operations.SavedView", "state") == {}


def test_updates_preserve_ownership_and_audit_without_copying_private_filters():
    space = make_space("saved-update")
    owner = make_member("saved-update-owner", space)
    peer = make_member("saved-update-peer", space)
    client = authenticated_client(owner)
    created = client.post(url(space), payload(), format="json")
    assert created.status_code == 201
    response = client.patch(url(space, created.data["id"]),
                            {"name": "Personal", "owner": peer.pk, "state": {"q": "private@example.test"}},
                            format="json")
    assert response.status_code == 200, response.data
    row = SavedView.objects.get(pk=created.data["id"])
    assert row.owner_id == owner.pk and row.name == "Personal"
    log = AuditLog.objects.get(action="saved_view.updated", target_id=str(row.pk))
    assert log.actor_id == owner.pk and log.makerspace_id == space.pk
    assert "private@example.test" not in str(log.meta)


def test_former_manager_must_unshare_before_editing_a_published_view():
    space = make_space("saved-demotion")
    manager = make_member("saved-demotion-owner", space)
    client = authenticated_client(manager)
    created = client.post(url(space), payload(shared=True), format="json")
    assert created.status_code == 201
    membership = manager.makerspace_memberships.get(makerspace=space)
    membership.role = "inventory_manager"
    membership.save(update_fields=["role"])
    detail = url(space, created.data["id"])
    assert client.patch(detail, {"name": "Published edit"}, format="json").status_code == 403
    assert client.patch(detail, {"shared": False}, format="json").status_code == 200
    assert client.patch(detail, {"name": "Personal edit"}, format="json").status_code == 200


@pytest.mark.django_db(transaction=True)
def test_source_freeze_blocks_saved_view_writes_but_leaves_reads_available():
    from tests.tenant_migration.source_gate_helpers import close_gate

    space = make_space("saved-frozen")
    owner = make_member("saved-frozen-owner", space)
    client = authenticated_client(owner)
    created = client.post(url(space), payload(), format="json")
    assert created.status_code == 201
    close_gate(space, owner)
    assert client.get(url(space) + "?entity=inventory").status_code == 200
    detail = url(space, created.data["id"])
    for response in (client.post(url(space), payload(), format="json"),
                     client.patch(detail, {"name": "Frozen"}, format="json"), client.delete(detail)):
        assert response.status_code == 423
    assert SavedView.objects.get(pk=created.data["id"]).name == "Low stock"
    assert not AuditLog.objects.filter(action__in=["saved_view.updated", "saved_view.deleted"]).exists()


def test_payment_due_filters_survive_saved_view_round_trip():
    space = make_space("saved-payment-due")
    owner = make_member("saved-payment-due-owner", space)
    client = authenticated_client(owner)
    state = {"status": "pending", "due_state": "overdue", "ordering": "due_at", "page": "2"}
    created = client.post(url(space), payload(name="Overdue charges", entity="payments", state=state), format="json")
    assert created.status_code == 201, created.data
    assert client.get(url(space, created.data["id"])).data["state"] == state


def test_columns_and_density_survive_saved_view_round_trip():
    space = make_space("saved-columns")
    client = authenticated_client(make_member("saved-columns-owner", space))
    state = {"columns": "name,available_quantity,actions", "density": "compact", "q": "drill"}
    created = client.post(url(space), payload(state=state), format="json")
    assert created.status_code == 201, created.data
    assert client.get(url(space, created.data["id"])).data["state"] == state


@pytest.mark.parametrize("state", [{"density": "tiny"}, {"columns": "name,name"}, {"columns": "name,<script>"}, {"columns": "name,,actions"}])
def test_invalid_presentation_state_is_refused(state):
    space = make_space("saved-bad-columns")
    client = authenticated_client(make_member("saved-bad-columns-owner", space))
    assert client.post(url(space), payload(state=state), format="json").status_code == 400
