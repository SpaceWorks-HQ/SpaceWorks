import pytest

from apps.accounts.models import User
from apps.makerspaces.models import MakerspaceMembership
from apps.procurement.models import ToBuyItem
from tests.return_helpers import (
    authenticated_client,
    make_member,
    make_print_manager,
    make_space,
    make_user,
)
from tests.handout_roles import make_handout_member

pytestmark = pytest.mark.django_db


def list_url(makerspace):
    return f"/api/v1/procurement/makerspace/{makerspace.id}/to-buy"


def detail_url(item):
    return f"/api/v1/procurement/to-buy/{item.id}"


def export_url(makerspace):
    return f"/api/v1/procurement/makerspace/{makerspace.id}/to-buy/export"


def make_space_manager(username, makerspace):
    return make_member(
        username,
        makerspace,
        membership_role=MakerspaceMembership.Role.SPACE_MANAGER,
        role=User.Role.SPACE_MANAGER,
    )


def make_inventory_manager(username, makerspace):
    return make_member(
        username,
        makerspace,
        membership_role=MakerspaceMembership.Role.INVENTORY_MANAGER,
        role=User.Role.REQUESTER,
    )


def make_guest_admin(username, makerspace):
    return make_handout_member(username, makerspace)


def make_superadmin(username):
    return make_user(
        username,
        role=User.Role.SUPERADMIN,
        access_status=User.AccessStatus.ACTIVE,
    )


def test_print_manager_adds_printing_item_and_sees_only_printing():
    space = make_space("proc-pm")
    manager = make_print_manager("proc-pm-mgr", space)
    # A hardware item already on the list (added directly) must stay hidden.
    ToBuyItem.objects.create(makerspace=space, kind=ToBuyItem.Kind.HARDWARE, name="Drill bits")

    client = authenticated_client(manager)
    create = client.post(list_url(space), {"name": "PLA filament", "quantity": 3, "link": "https://x.test"}, format="json")
    assert create.status_code == 201
    # Kind auto-tagged from the print-manager role, not the request body.
    assert create.data["kind"] == ToBuyItem.Kind.PRINTING

    listed = client.get(list_url(space))
    assert listed.status_code == 200
    names = {row["name"] for row in listed.data}
    assert names == {"PLA filament"}  # hardware item excluded


def test_space_manager_sees_both_streams_and_defaults_to_hardware():
    space = make_space("proc-sm")
    admin = make_space_manager("proc-sm-mgr", space)
    ToBuyItem.objects.create(makerspace=space, kind=ToBuyItem.Kind.PRINTING, name="Nozzle")

    client = authenticated_client(admin)
    create = client.post(list_url(space), {"name": "Soldering iron", "quantity": 1}, format="json")
    assert create.status_code == 201
    assert create.data["kind"] == ToBuyItem.Kind.HARDWARE  # admin defaults to hardware

    listed = client.get(list_url(space))
    kinds = {row["name"]: row["kind"] for row in listed.data}
    assert kinds == {"Nozzle": "printing", "Soldering iron": "hardware"}  # both streams


def test_space_manager_can_target_printing_stream_explicitly():
    space = make_space("proc-sm-kind")
    admin = make_space_manager("proc-sm-kind-mgr", space)
    client = authenticated_client(admin)
    create = client.post(f"{list_url(space)}?kind=printing", {"name": "Spool", "quantity": 2}, format="json")
    assert create.status_code == 201
    assert create.data["kind"] == ToBuyItem.Kind.PRINTING


def test_inventory_manager_sees_hardware_only_and_cannot_touch_printing():
    space = make_space("proc-im")
    inv = make_inventory_manager("proc-im-mgr", space)
    printing_item = ToBuyItem.objects.create(makerspace=space, kind=ToBuyItem.Kind.PRINTING, name="Hotend")

    client = authenticated_client(inv)
    create = client.post(list_url(space), {"name": "Calipers", "quantity": 1}, format="json")
    assert create.status_code == 201
    assert create.data["kind"] == ToBuyItem.Kind.HARDWARE

    listed = client.get(list_url(space))
    assert {row["name"] for row in listed.data} == {"Calipers"}
    # Printing item is not viewable -> 404 (not 403) on detail.
    assert client.get(detail_url(printing_item)).status_code == 404
    assert client.patch(detail_url(printing_item), {"status": "received"}, format="json").status_code == 404


def test_print_manager_cannot_edit_hardware_item():
    space = make_space("proc-pm-edit")
    manager = make_print_manager("proc-pm-edit-mgr", space)
    hardware_item = ToBuyItem.objects.create(makerspace=space, kind=ToBuyItem.Kind.HARDWARE, name="Wrench")
    client = authenticated_client(manager)
    assert client.patch(detail_url(hardware_item), {"status": "received"}, format="json").status_code == 404
    assert client.delete(detail_url(hardware_item)).status_code == 404


def test_guest_admin_has_no_procurement_access():
    space = make_space("proc-guest")
    guest = make_guest_admin("proc-guest-user", space)
    ToBuyItem.objects.create(makerspace=space, kind=ToBuyItem.Kind.HARDWARE, name="Tape")
    client = authenticated_client(guest)
    assert client.get(list_url(space)).data == []
    assert client.post(list_url(space), {"name": "x", "quantity": 1}, format="json").status_code == 403
    assert client.get(export_url(space)).status_code == 403


def test_cross_tenant_items_are_not_visible():
    space_a = make_space("proc-x-a")
    space_b = make_space("proc-x-b")
    admin_a = make_space_manager("proc-x-a-mgr", space_a)
    item_b = ToBuyItem.objects.create(makerspace=space_b, kind=ToBuyItem.Kind.HARDWARE, name="B item")
    client = authenticated_client(admin_a)
    assert client.get(list_url(space_b)).data == []
    assert client.get(detail_url(item_b)).status_code == 404




def test_list_and_export_filter_by_status():
    space = make_space("proc-status-filter")
    admin = make_space_manager("proc-status-filter-mgr", space)
    ToBuyItem.objects.create(makerspace=space, kind=ToBuyItem.Kind.HARDWARE, name="Requested item")
    ToBuyItem.objects.create(
        makerspace=space,
        kind=ToBuyItem.Kind.HARDWARE,
        name="Received item",
        status=ToBuyItem.Status.RECEIVED,
    )

    client = authenticated_client(admin)
    listed = client.get(f"{list_url(space)}?status=requested")
    exported = client.get(f"{export_url(space)}?status=requested")

    assert listed.status_code == 200
    assert [row["name"] for row in listed.data] == ["Requested item"]
    body = exported.content.decode()
    assert "Requested item" in body
    assert "Received item" not in body
def test_export_csv_scoped_to_viewable_kinds():
    space = make_space("proc-csv")
    manager = make_print_manager("proc-csv-mgr", space)
    ToBuyItem.objects.create(makerspace=space, kind=ToBuyItem.Kind.PRINTING, name="Filament", quantity=2)
    ToBuyItem.objects.create(makerspace=space, kind=ToBuyItem.Kind.HARDWARE, name="Hidden hardware")

    response = authenticated_client(manager).get(export_url(space))
    assert response.status_code == 200
    assert response["Content-Type"] == "text/csv"
    body = response.content.decode()
    assert "Filament" in body
    assert "Hidden hardware" not in body  # hardware stream excluded for print manager


def test_export_xlsx_returns_spreadsheet_and_invalid_format_400():
    space = make_space("proc-xlsx")
    manager = make_space_manager("proc-xlsx-mgr", space)
    ToBuyItem.objects.create(makerspace=space, kind=ToBuyItem.Kind.HARDWARE, name="Drill bits", quantity=4)
    client = authenticated_client(manager)

    xlsx = client.get(f"{export_url(space)}?format=xlsx")
    assert xlsx.status_code == 200
    assert (
        xlsx["Content-Type"]
        == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

    bad = client.get(f"{export_url(space)}?format=pdf")
    assert bad.status_code == 400
    assert "format" in bad.data


def test_negative_estimated_cost_and_zero_quantity_are_rejected():
    space = make_space("proc-validate")
    admin = make_space_manager("proc-validate-mgr", space)
    client = authenticated_client(admin)

    bad_cost = client.post(list_url(space), {"name": "Item", "quantity": 1, "estimated_unit_cost": "-1.00"}, format="json")
    assert bad_cost.status_code == 400
    assert "estimated_unit_cost" in bad_cost.data

    bad_qty = client.post(list_url(space), {"name": "Item", "quantity": 0}, format="json")
    assert bad_qty.status_code == 400
    assert "quantity" in bad_qty.data


def test_disabled_procurement_module_blocks_the_api():
    space = make_space("proc-disabled")
    space.enabled_modules = [m for m in space.enabled_modules if m != "procurement"]
    space.save(update_fields=["enabled_modules"])
    admin = make_space_manager("proc-disabled-mgr", space)
    client = authenticated_client(admin)
    assert client.get(list_url(space)).status_code == 400
    assert client.post(list_url(space), {"name": "x", "quantity": 1}, format="json").status_code == 400
    assert client.get(export_url(space)).status_code == 400


def test_csv_export_escapes_formula_injection():
    space = make_space("proc-inject")
    admin = make_space_manager("proc-inject-mgr", space)
    ToBuyItem.objects.create(makerspace=space, kind=ToBuyItem.Kind.HARDWARE, name="=cmd|' /c calc'!A1")
    response = authenticated_client(admin).get(export_url(space))
    assert response.status_code == 200
    body = response.content.decode()
    # The dangerous cell is neutralized with a leading apostrophe.
    assert "'=cmd" in body


def test_superadmin_sees_both_and_can_target_either_kind():
    space = make_space("proc-super")
    superadmin = make_superadmin("proc-super-user")
    ToBuyItem.objects.create(makerspace=space, kind=ToBuyItem.Kind.HARDWARE, name="HW")
    ToBuyItem.objects.create(makerspace=space, kind=ToBuyItem.Kind.PRINTING, name="PR")

    client = authenticated_client(superadmin)
    listed = client.get(list_url(space))
    assert {row["name"] for row in listed.data} == {"HW", "PR"}
    create = client.post(f"{list_url(space)}?kind=printing", {"name": "New spool", "quantity": 1}, format="json")
    assert create.status_code == 201
    assert create.data["kind"] == ToBuyItem.Kind.PRINTING


def test_received_status_delete_and_export_all_succeed():
    space = make_space("proc-regression")
    admin = make_space_manager("proc-regression-mgr", space)
    client = authenticated_client(admin)

    created = client.post(
        list_url(space),
        {"name": "Replacement chuck", "quantity": 1},
        format="json",
    )
    assert created.status_code == 201
    item = ToBuyItem.objects.get(id=created.data["id"])

    received = client.patch(detail_url(item), {"status": ToBuyItem.Status.RECEIVED}, format="json")
    csv_export = client.get(export_url(space))
    xlsx_export = client.get(f"{export_url(space)}?format=xlsx")
    deleted = client.delete(detail_url(item))

    assert received.status_code == 200
    assert csv_export.status_code == 200
    assert xlsx_export.status_code == 200
    assert deleted.status_code == 204



def test_lifecycle_status_mapping_migration_functions():
    import importlib
    from django.apps import apps

    migration = importlib.import_module("apps.procurement.migrations.0003_tobuy_lifecycle_receipts")
    space = make_space("proc-migration-map")
    pending = ToBuyItem.objects.create(makerspace=space, kind=ToBuyItem.Kind.HARDWARE, name="Old pending", status="pending")
    bought = ToBuyItem.objects.create(makerspace=space, kind=ToBuyItem.Kind.HARDWARE, name="Old bought", status="bought")

    migration.forward_statuses(apps, None)
    pending.refresh_from_db()
    bought.refresh_from_db()
    assert pending.status == ToBuyItem.Status.REQUESTED
    assert bought.status == ToBuyItem.Status.RECEIVED

    approved = ToBuyItem.objects.create(makerspace=space, kind=ToBuyItem.Kind.HARDWARE, name="Approved", status=ToBuyItem.Status.APPROVED)
    migration.reverse_statuses(apps, None)
    pending.refresh_from_db()
    bought.refresh_from_db()
    approved.refresh_from_db()
    assert bought.status == "bought"
    assert pending.status == "pending"
    assert approved.status == "pending"


def test_lifecycle_stamps_ordered_and_received_and_persists_purchase_fields():
    space = make_space("proc-lifecycle")
    manager = make_inventory_manager("proc-lifecycle-manager", space)
    item = ToBuyItem.objects.create(makerspace=space, kind=ToBuyItem.Kind.HARDWARE, name="Router")
    client = authenticated_client(manager)

    ordered = client.patch(
        detail_url(item),
        {
            "status": ToBuyItem.Status.ORDERED,
            "vendor_name": "Tool Vendor",
            "actual_unit_cost": "42.50",
        },
        format="json",
    )
    received = client.patch(detail_url(item), {"status": ToBuyItem.Status.RECEIVED}, format="json")
    item.refresh_from_db()

    assert ordered.status_code == 200
    assert ordered.data["ordered_at"] is not None
    assert ordered.data["purchaser"] == manager.id
    assert ordered.data["purchaser_username"] == manager.username
    assert ordered.data["vendor_name"] == "Tool Vendor"
    assert ordered.data["actual_unit_cost"] == "42.50"
    assert received.status_code == 200
    assert received.data["received_at"] is not None
    assert item.ordered_at is not None
    assert item.received_at is not None
    assert item.purchaser == manager
    assert item.vendor_name == "Tool Vendor"
    assert str(item.actual_unit_cost) == "42.50"
