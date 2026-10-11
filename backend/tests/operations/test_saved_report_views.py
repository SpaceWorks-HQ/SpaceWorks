"""Report saved preferences reuse list preferences while enforcing report authority."""

import pytest

from apps.audit.models import AuditLog
from apps.makerspaces.module_install import install_module
from apps.operations.models import SavedView
from tests.module_helpers import disable_module
from tests.return_helpers import authenticated_client, make_member, make_space

pytestmark = pytest.mark.django_db


def url(space, pk=None):
    base = f"/api/v1/admin/makerspaces/{space.pk}/saved-report-views"
    return f"{base}/{pk}" if pk else base


def payload(**extra):
    return {"name": "Monthly members", "state": {"report_key": "member-retention", "grain": "day",
        "filters": {"start": "2025-01-01", "end": "2026-06-30", "months": 6},
        "columns": ["cohort_month", "retained_members"]}, **extra}


def setup(slug):
    space = make_space(slug)
    install_module(space, "membership")
    owner = make_member(f"{slug}-owner", space)
    return space, owner, authenticated_client(owner)


def test_private_report_view_round_trip_reuses_saved_view_and_audits_every_write():
    space, owner, client = setup("saved-report-private")
    peer = make_member("saved-report-peer", space)
    response = client.post(url(space), payload(), format="json")
    assert response.status_code == 201, response.data
    row = SavedView.objects.get(pk=response.data["id"])
    assert row.entity == "report" and row.owner_id == owner.pk
    assert row.state == payload()["state"]
    assert client.get(url(space, row.pk)).data["state"] == row.state
    assert authenticated_client(peer).get(url(space)).data["results"] == []
    assert authenticated_client(peer).get(url(space, row.pk)).status_code == 404
    changed = client.patch(url(space, row.pk), {"name": "Renamed", "state": {"columns": ["cohort_month"]}}, format="json")
    assert changed.status_code == 200, changed.data
    assert changed.data["state"]["filters"] == row.state["filters"]
    assert client.delete(url(space, row.pk)).status_code == 204
    assert set(AuditLog.objects.filter(target_type="operations.savedview", target_id=str(row.pk)).values_list("action", flat=True)) == {
        "saved_view.created", "saved_view.updated", "saved_view.deleted"}


def test_shared_report_view_reauthorizes_reader_and_owner_and_refuses_peer_writes():
    space, owner, client = setup("saved-report-shared")
    peer = make_member("saved-report-shared-peer", space)
    peer_client = authenticated_client(peer)
    response = client.post(url(space), payload(shared=True), format="json")
    assert response.status_code == 201, response.data
    pk = response.data["id"]
    assert peer_client.get(url(space, pk)).status_code == 200
    assert peer_client.patch(url(space, pk), {"name": "Take over"}, format="json").status_code == 403
    assert peer_client.delete(url(space, pk)).status_code == 403
    owner.makerspace_memberships.filter(makerspace=space).update(status="revoked")
    assert peer_client.get(url(space, pk)).status_code == 403
    assert peer_client.get(url(space)).data["results"] == []


def test_saved_report_view_tenant_module_and_feature_gates():
    space, owner, client = setup("saved-report-gates")
    other = make_space("saved-report-gates-other")
    created = client.post(url(space), payload(), format="json")
    pk = created.data["id"]
    assert client.get(url(other, pk)).status_code == 404
    assert client.post(url(other), payload(), format="json").status_code == 404
    disable_module(space, "membership")
    assert client.get(url(space, pk)).status_code == 400
    disable_module(space, "reports")
    assert client.get(url(space)).status_code == 400
    install_module(space, "reports")
    space.refresh_from_db()
    space.enabled_features = [key for key in space.enabled_features if key != "reports.saved_views"]
    space.save(update_fields=["enabled_features"])
    assert client.post(url(space), payload(), format="json").status_code == 400


@pytest.mark.parametrize("state", [
    {"report_key": "member-retention", "sql": "select"},
    {"report_key": "member-retention", "filters": {"email": "PII@example.test"}},
    {"report_key": "member-retention", "columns": ["username"]},
    {"report_key": "member-retention", "filters": {"months": 0}},
    {"report_key": "member-retention", "filters": {"start": "2026-01-02", "end": "2026-01-01"}},
    {"report_key": "membership-revenue", "grain": "day"},
    {"report_key": "audit-trail"},
    {"report_key": "missing"},
])
def test_saved_report_state_rejects_pii_unknown_columns_invalid_ranges_and_unsupported_reports(state):
    space, _owner, client = setup("saved-report-invalid")
    assert client.post(url(space), payload(state=state), format="json").status_code == 400
    assert not SavedView.objects.exists()


def test_report_saved_views_are_paginated_and_portable_preferences_reset():
    from apps.data_export.guards import validate_semantic_references, validate_user_edges
    from apps.tenant_migration.target_projection import TARGET_FIELD_PROJECTION
    space, owner, client = setup("saved-report-pages")
    SavedView.objects.bulk_create([SavedView(makerspace=space, owner=owner, name=f"View {number}", entity="report", state=payload()["state"]) for number in range(25)])
    response = client.get(url(space))
    assert response.data["count"] == 25 and len(response.data["results"]) == 24
    assert response.data["next"]
    validate_user_edges()
    validate_semantic_references()
    for field, expected in [("state", {}), ("shared", False)]:
        assert TARGET_FIELD_PROJECTION[("operations.SavedView", field)].resolved_value("operations.SavedView", field) == expected


@pytest.mark.django_db(transaction=True)
def test_source_freeze_blocks_report_preference_writes_and_allows_reads():
    from tests.tenant_migration.source_gate_helpers import close_gate
    space, owner, client = setup("saved-report-freeze")
    created = client.post(url(space), payload(), format="json")
    assert created.status_code == 201
    detail = url(space, created.data["id"])
    close_gate(space, owner)
    assert client.get(detail).status_code == 200
    assert client.post(url(space), payload(), format="json").status_code == 423
    assert client.patch(detail, {"name": "Frozen"}, format="json").status_code == 423
    assert client.delete(detail).status_code == 423


def test_only_manager_may_share_and_report_readers_cannot_open_finance_views():
    space, _owner, client = setup("saved-report-role-floor")
    reader = make_member("saved-report-role-floor-reader", space, membership_role="inventory_manager")
    reader_client = authenticated_client(reader)
    assert reader_client.post(url(space), payload(shared=True), format="json").status_code == 403
    created = client.post(url(space), payload(shared=True, state={"report_key": "membership-revenue", "grain": "month", "filters": {}, "columns": ["mrr"]}), format="json")
    assert created.status_code == 201, created.data
    assert reader_client.get(url(space, created.data["id"])).status_code == 404
    assert reader_client.get(url(space)).data["results"] == []


def test_saved_mrr_view_defaults_to_month_and_partial_edits_preserve_state():
    space, _owner, client = setup("saved-report-default-month")
    response = client.post(url(space), payload(state={"report_key": "membership-revenue"}), format="json")
    assert response.status_code == 201, response.data
    pk = response.data["id"]
    assert response.data["state"]["grain"] == "month"
    changed = client.patch(url(space, pk), {"state": {"columns": ["mrr"]}}, format="json")
    assert changed.status_code == 200, changed.data
    assert changed.data["state"] == {"report_key": "membership-revenue", "grain": "month", "filters": {}, "columns": ["mrr"]}


@pytest.mark.django_db(transaction=True)
def test_report_module_purge_deletes_only_this_spaces_report_preferences():
    from apps.accounts.models import User
    from apps.makerspaces.module_install import uninstall_module
    from apps.makerspaces.module_purge import purge_module

    space, owner, client = setup("saved-report-purge")
    other = make_space("saved-report-purge-other")
    created = client.post(url(space), payload(), format="json")
    assert created.status_code == 201, created.data
    report_id = created.data["id"]
    staff_view = SavedView.objects.create(makerspace=space, owner=owner, name="Inventory", entity="inventory", state={})
    foreign = SavedView.objects.create(makerspace=other, owner=owner, name="Other report", entity="report", state=payload()["state"])
    actor = User.objects.create_superuser(username="saved-report-purge-admin", email="purge@example.test", password="password")
    uninstall_module(space, "reports")
    counts = purge_module(space, "reports", actor)
    assert counts["saved_report_views"] == 1
    assert not SavedView.objects.filter(pk=report_id).exists()
    assert SavedView.objects.filter(pk__in=[staff_view.pk, foreign.pk]).count() == 2
