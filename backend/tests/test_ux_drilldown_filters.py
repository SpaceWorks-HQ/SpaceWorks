from datetime import timedelta

import pytest
from django.utils import timezone

from apps.integrations.models import EmailLog
from apps.machines.models import Machine, MachineServiceRequest, MachineType, ServiceQueue
from apps.operations.models import StocktakeSession
from tests.return_helpers import authenticated_client, make_member, make_product, make_space

pytestmark = pytest.mark.django_db


def test_print_type_drilldown_includes_queue_jobs_without_slug_collision():
    space = make_space("ux-assigned-print")
    space.enabled_modules = sorted(set(space.enabled_modules) | {"machines", "machine_service", "printing"})
    space.save(update_fields=["enabled_modules"])
    actor = make_member("ux-assigned-print-manager", space)
    printer = MachineType.objects.get(makerspace__isnull=True, slug="3d_printer")
    collision = MachineType.objects.create(makerspace=space, slug="3d_printer", name="Local type")
    wanted = None
    for kind in (printer, collision):
        machine = Machine.objects.create(makerspace=space, machine_type=kind, name=kind.name)
        queue = ServiceQueue.objects.create(makerspace=space, machine_type=kind, name=kind.name)
        row = MachineServiceRequest.objects.create(makerspace=space, requester=actor, queue=queue,
            requester_name=actor.username, title=kind.name, status="in_progress", assigned_machine=machine)
        if kind.pk == printer.pk:
            wanted = row
    path = f"/api/v1/admin/makerspaces/{space.pk}/machine-service/requests"
    response = authenticated_client(actor).get(path, {"status": "in_progress", "machine_type_id": printer.pk})
    assert response.status_code == 200
    assert [row["id"] for row in response.data] == [wanted.pk]


def test_out_of_stock_drilldown_means_exactly_zero_and_includes_archived_when_requested():
    space = make_space("ux-stock-zero")
    actor = make_member("ux-stock-zero-manager", space)
    wanted = make_product(space, name="Empty", total_quantity=1, available_quantity=0, issued_quantity=1)
    archived = make_product(space, name="Archived", total_quantity=1, available_quantity=0, issued_quantity=1, is_archived=True)
    make_product(space, name="Limited", total_quantity=10, available_quantity=1, issued_quantity=9)
    client = authenticated_client(actor)
    path = f"/api/v1/admin/makerspace/{space.pk}/inventory"
    response = client.get(path, {"out_of_stock": "true", "archived": "all"})
    assert response.status_code == 200 and response.data["count"] == 2
    assert {row["id"] for row in response.data["results"]} == {wanted.pk, archived.pk}
    assert client.get(path, {"out_of_stock": "invented"}).status_code == 400


def test_stocktake_status_filter_is_validated_and_tenant_scoped():
    space, other = make_space("ux-stocktake"), make_space("ux-stocktake-other")
    space.enabled_modules = sorted(set(space.enabled_modules) | {"stocktake"})
    space.save(update_fields=["enabled_modules"])
    actor = make_member("ux-stocktake-manager", space)
    wanted = StocktakeSession.objects.create(makerspace=space, status="completed", started_by=actor)
    StocktakeSession.objects.create(makerspace=space, status="counting", started_by=actor)
    StocktakeSession.objects.create(makerspace=other, status="completed", started_by=actor)
    client = authenticated_client(actor)
    path = f"/api/v1/admin/makerspace/{space.pk}/stocktakes"
    response = client.get(path, {"status": "completed"})
    assert response.status_code == 200 and response.data["count"] == 1
    assert response.data["results"][0]["id"] == wanted.pk
    assert client.get(path, {"status": "invented"}).status_code == 400
    other.enabled_modules = sorted(set(other.enabled_modules) | {"stocktake"})
    other.save(update_fields=["enabled_modules"])
    before = StocktakeSession.objects.count()
    assert client.post(f"/api/v1/admin/makerspace/{other.pk}/stocktakes",
                       {"notes": "Foreign creation"}, format="json").status_code == 404
    assert StocktakeSession.objects.count() == before


def test_dashboard_email_filter_excludes_old_failures_and_other_tenants():
    space, other = make_space("ux-email"), make_space("ux-email-other")
    actor = make_member("ux-email-manager", space)
    def log(lab, status="failed"):
        return EmailLog.objects.create(makerspace=lab, to_email="member@example.test",
                                       subject="Test", stream="hardware", event="accepted", status=status)
    recent = log(space)
    old = log(space)
    EmailLog.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=8))
    log(space, "sent")
    log(other)
    client = authenticated_client(actor)
    path = f"/api/v1/admin/makerspace/{space.pk}/email-logs"
    response = client.get(path, {"status": "failed", "recent_days": "7"})
    assert response.status_code == 200 and response.data["count"] == 1
    assert response.data["results"][0]["id"] == recent.pk
    assert client.get(path, {"recent_days": "0"}).status_code == 400
    assert client.get(path, {"recent_days": "nonsense"}).status_code == 400


def test_archive_compensation_persists_both_changes_with_scoped_audit_rows():
    from apps.audit.models import AuditLog

    space, other = make_space("ux-archive-undo"), make_space("ux-archive-foreign")
    actor = make_member("ux-archive-manager", space)
    product = make_product(space)
    foreign = make_product(other)
    client = authenticated_client(actor)
    before = AuditLog.objects.filter(makerspace=space, action="inventory.updated").count()
    url = f"/api/v1/admin/inventory/{product.pk}"
    for archived in (True, False):
        response = client.patch(url, {"is_archived": archived}, format="json")
        assert response.status_code == 200
        product.refresh_from_db()
        assert product.is_archived is archived
    assert AuditLog.objects.filter(makerspace=space, action="inventory.updated", actor=actor).count() == before + 2
    assert client.patch(f"/api/v1/admin/inventory/{foreign.pk}", {"is_archived": True}, format="json").status_code == 404
    foreign.refresh_from_db()
    assert foreign.is_archived is False


def test_archive_compensation_refuses_module_off_without_changing_state():
    from apps.audit.models import AuditLog

    space = make_space("ux-archive-off")
    actor = make_member("ux-archive-off-manager", space)
    product = make_product(space)
    space.enabled_modules = []
    space.save(update_fields=["enabled_modules"])
    before = AuditLog.objects.count()
    response = authenticated_client(actor).patch(f"/api/v1/admin/inventory/{product.pk}", {"is_archived": True}, format="json")
    assert response.status_code == 400
    product.refresh_from_db()
    assert product.is_archived is False
    assert AuditLog.objects.count() == before


def test_dashboard_inventory_export_preserves_all_archives_and_tenant_scope():
    import csv
    import io

    space, other = make_space("ux-export"), make_space("ux-export-other")
    actor = make_member("ux-export-manager", space)
    make_product(space, name="Empty", total_quantity=1, available_quantity=0, issued_quantity=1)
    make_product(space, name="Archived", total_quantity=1, available_quantity=0, issued_quantity=1, is_archived=True)
    make_product(space, name="In stock")
    make_product(other, name="Foreign", total_quantity=1, available_quantity=0, issued_quantity=1)
    response = authenticated_client(actor).get(f"/api/v1/admin/makerspace/{space.pk}/inventory/export",
                                              {"format": "csv", "archived": "all", "out_of_stock": "true"})
    assert response.status_code == 200
    rows = list(csv.reader(io.StringIO(response.content.decode("utf-8-sig"))))
    assert [row[0] for row in rows[1:-1]] == ["Archived", "Empty"]
