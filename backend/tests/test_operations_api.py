import io
import zipfile

from openpyxl import load_workbook

import pytest

from apps.accounts.models import User
from apps.boxes.models import Box, BoxScan, QrCode, QrScanEvent
from apps.inventory.models import InventoryAsset, InventoryProduct, TrackingMode
from apps.operations.models import (
    InventoryAdjustment,
    QrPrintBatch,
    QrPrintBatchItem,
    StockTransfer,
    StocktakeLedgerEntry,
    StocktakeSession,
)
from tests.return_helpers import authenticated_client, make_box, make_member, make_product, make_space, make_user
from tests.handout_roles import make_handout_member

pytestmark = pytest.mark.django_db


def _cross_transfer(superadmin, source, dest, product, quantity):
    return authenticated_client(superadmin).post(
        f"/api/v1/admin/makerspace/{source.id}/stock-transfers",
        {
            "destination_makerspace_id": dest.id,
            "reason": "Lend to partner space",
            "lines": [{"product_id": product.id, "quantity": quantity}],
        },
        format="json",
    )


def test_cross_makerspace_transfer_moves_quantity_to_destination_product():
    source = make_space("xfer-src")
    dest = make_space("xfer-dst")
    superadmin = make_user("xfer-super", role=User.Role.SUPERADMIN, access_status=User.AccessStatus.ACTIVE)
    product = make_product(source, name="Soldering Iron", total_quantity=10, available_quantity=10)

    created = _cross_transfer(superadmin, source, dest, product, 4)

    assert created.status_code == 201
    product.refresh_from_db()
    assert product.available_quantity == 6 and product.total_quantity == 6
    moved = InventoryProduct.objects.get(makerspace=dest, name="Soldering Iron")
    assert moved.available_quantity == 4 and moved.total_quantity == 4
    assert moved.is_public is False  # destination opts in explicitly
    assert InventoryAdjustment.objects.filter(makerspace=source, delta_available=-4).exists()
    assert InventoryAdjustment.objects.filter(makerspace=dest, delta_available=4).exists()


def test_cross_makerspace_transfer_rejects_more_than_available():
    source = make_space("xfer-src2")
    dest = make_space("xfer-dst2")
    superadmin = make_user("xfer-super2", role=User.Role.SUPERADMIN, access_status=User.AccessStatus.ACTIVE)
    product = make_product(source, name="Caliper", total_quantity=3, available_quantity=3)

    response = _cross_transfer(superadmin, source, dest, product, 5)

    assert response.status_code == 400
    product.refresh_from_db()
    assert product.available_quantity == 3  # unchanged


def test_cross_makerspace_transfer_credits_existing_destination_product():
    source = make_space("xfer-src3")
    dest = make_space("xfer-dst3")
    superadmin = make_user("xfer-super3", role=User.Role.SUPERADMIN, access_status=User.AccessStatus.ACTIVE)
    product = make_product(source, name="Multimeter", total_quantity=10, available_quantity=10)
    existing = make_product(dest, name="Multimeter", total_quantity=2, available_quantity=2, is_public=False)

    created = _cross_transfer(superadmin, source, dest, product, 3)

    assert created.status_code == 201
    existing.refresh_from_db()
    assert existing.available_quantity == 5 and existing.total_quantity == 5
    # no duplicate product created in the destination
    assert InventoryProduct.objects.filter(makerspace=dest, name="Multimeter").count() == 1


def test_cross_makerspace_transfer_does_not_credit_archived_destination_product():
    source = make_space("xfer-src-archived")
    dest = make_space("xfer-dst-archived")
    superadmin = make_user(
        "xfer-super-archived",
        role=User.Role.SUPERADMIN,
        access_status=User.AccessStatus.ACTIVE,
    )
    product = make_product(source, name="Oscilloscope", total_quantity=10, available_quantity=10)
    archived = make_product(
        dest,
        name="Oscilloscope",
        total_quantity=2,
        available_quantity=2,
        is_public=False,
        is_archived=True,
    )

    created = _cross_transfer(superadmin, source, dest, product, 4)

    assert created.status_code == 201
    product.refresh_from_db()
    archived.refresh_from_db()
    assert product.available_quantity == 6 and product.total_quantity == 6
    assert archived.available_quantity == 2 and archived.total_quantity == 2
    fresh = InventoryProduct.objects.get(
        makerspace=dest,
        name="Oscilloscope",
        is_archived=False,
    )
    assert fresh.available_quantity == 4 and fresh.total_quantity == 4
    assert fresh.is_public is False
    assert (
        InventoryProduct.objects.filter(makerspace=dest, name="Oscilloscope")
        .count()
        == 2
    )
    assert (
        product.available_quantity
        + archived.available_quantity
        + fresh.available_quantity
        == 12
    )


def test_cross_makerspace_transfer_rejects_individual_destination_match():
    source = make_space("xfer-src5")
    dest = make_space("xfer-dst5")
    superadmin = make_user("xfer-super5", role=User.Role.SUPERADMIN, access_status=User.AccessStatus.ACTIVE)
    product = make_product(source, name="Drill", total_quantity=10, available_quantity=10)
    make_product(dest, name="Drill", total_quantity=1, available_quantity=1, tracking_mode=TrackingMode.INDIVIDUAL)

    response = _cross_transfer(superadmin, source, dest, product, 2)

    assert response.status_code == 400
    product.refresh_from_db()
    assert product.available_quantity == 10  # source untouched


def test_cross_makerspace_transfer_rejects_individual_tracking():
    source = make_space("xfer-src4")
    dest = make_space("xfer-dst4")
    superadmin = make_user("xfer-super4", role=User.Role.SUPERADMIN, access_status=User.AccessStatus.ACTIVE)
    product = make_product(
        source, name="Arduino", total_quantity=5, available_quantity=5, tracking_mode=TrackingMode.INDIVIDUAL
    )

    response = _cross_transfer(superadmin, source, dest, product, 1)

    assert response.status_code == 400


def _intra_transfer_payload(product, destination):
    return {
        "destination_container_id": destination.id,
        "reason": "Move to shelf",
        "lines": [{"product_id": product.id, "quantity": 1}],
    }


def test_intra_makerspace_transfer_allowed_for_edit_inventory_manager():
    # Intra-makerspace relocation (no destination_makerspace_id) is now a manager action
    # gated on EDIT_INVENTORY — it only moves stock between containers in the same tenant.
    makerspace = make_space("ops-transfer")
    manager = make_member("ops-transfer-manager", makerspace)
    product = make_product(makerspace)
    destination = make_box(makerspace, "Destination")

    created = authenticated_client(manager).post(
        f"/api/v1/admin/makerspace/{makerspace.id}/stock-transfers",
        _intra_transfer_payload(product, destination),
        format="json",
    )

    assert created.status_code == 201
    product.refresh_from_db()
    assert product.available_quantity == 9
    assert product.total_quantity == 9
    moved = InventoryProduct.objects.get(
        makerspace=makerspace,
        name=product.name,
        box=destination,
    )
    assert moved.available_quantity == 1
    assert moved.total_quantity == 1
    assert moved.is_public is False
    assert StockTransfer.objects.count() == 1


def test_partial_intra_makerspace_transfer_keeps_remaining_stock_in_source_box():
    makerspace = make_space("ops-transfer-split")
    manager = make_member("ops-transfer-split-manager", makerspace)
    source = make_box(makerspace, "Source")
    destination = make_box(makerspace, "Destination")
    product = make_product(
        makerspace,
        name="Header Pins",
        box=source,
        total_quantity=10,
        available_quantity=10,
    )

    response = authenticated_client(manager).post(
        f"/api/v1/admin/makerspace/{makerspace.id}/stock-transfers",
        {
            "source_container_id": source.id,
            "destination_container_id": destination.id,
            "reason": "Restock front shelf",
            "lines": [{"product_id": product.id, "quantity": 2}],
        },
        format="json",
    )

    assert response.status_code == 201
    product.refresh_from_db()
    moved = InventoryProduct.objects.get(
        makerspace=makerspace,
        name="Header Pins",
        box=destination,
    )
    assert (product.box_id, product.available_quantity, product.total_quantity) == (
        source.id,
        8,
        8,
    )
    assert (moved.available_quantity, moved.total_quantity) == (2, 2)


def test_intra_makerspace_transfer_merges_into_matching_destination_product():
    makerspace = make_space("ops-transfer-merge")
    manager = make_member("ops-transfer-merge-manager", makerspace)
    source = make_box(makerspace, "Source")
    destination = make_box(makerspace, "Destination")
    product = make_product(
        makerspace,
        name="Jumper Wires",
        box=source,
        total_quantity=10,
        available_quantity=10,
    )
    existing = make_product(
        makerspace,
        name="Jumper Wires",
        box=destination,
        total_quantity=3,
        available_quantity=3,
        is_public=False,
    )

    response = authenticated_client(manager).post(
        f"/api/v1/admin/makerspace/{makerspace.id}/stock-transfers",
        {
            "source_container_id": source.id,
            "destination_container_id": destination.id,
            "reason": "Top up destination shelf",
            "lines": [{"product_id": product.id, "quantity": 4}],
        },
        format="json",
    )

    assert response.status_code == 201
    product.refresh_from_db()
    existing.refresh_from_db()
    assert (product.available_quantity, product.total_quantity) == (6, 6)
    assert (existing.available_quantity, existing.total_quantity) == (7, 7)
    assert InventoryProduct.objects.filter(makerspace=makerspace, name="Jumper Wires").count() == 2


def test_intra_makerspace_transfer_rejects_more_than_available_stock():
    makerspace = make_space("ops-transfer-over")
    manager = make_member("ops-transfer-over-manager", makerspace)
    product = make_product(
        makerspace,
        name="Bearings",
        total_quantity=10,
        available_quantity=3,
        reserved_quantity=7,
    )
    destination = make_box(makerspace, "Destination")

    response = authenticated_client(manager).post(
        f"/api/v1/admin/makerspace/{makerspace.id}/stock-transfers",
        {
            "destination_container_id": destination.id,
            "reason": "Move reserved stock",
            "lines": [{"product_id": product.id, "quantity": 4}],
        },
        format="json",
    )

    assert response.status_code == 400
    product.refresh_from_db()
    assert (product.available_quantity, product.reserved_quantity, product.total_quantity) == (
        3,
        7,
        10,
    )
    assert InventoryProduct.objects.filter(makerspace=makerspace, box=destination).count() == 0


def test_intra_makerspace_transfer_denied_for_other_makerspace_manager():
    # Tenant scope: a manager of another makerspace cannot transfer in this one.
    makerspace = make_space("ops-transfer-own")
    other = make_space("ops-transfer-other")
    outsider = make_member("ops-transfer-outsider", other)
    product = make_product(makerspace)
    destination = make_box(makerspace, "Destination")

    response = authenticated_client(outsider).post(
        f"/api/v1/admin/makerspace/{makerspace.id}/stock-transfers",
        _intra_transfer_payload(product, destination),
        format="json",
    )

    assert response.status_code == 403
    assert StockTransfer.objects.count() == 0


def test_cross_makerspace_transfer_denied_for_non_superadmin_with_no_side_effects():
    # Cross-makerspace moves stay superadmin-only; a manager attempt must 403 BEFORE any
    # stock is deducted from the source product.
    source = make_space("ops-xfer-src")
    dest = make_space("ops-xfer-dst")
    manager = make_member("ops-xfer-manager", source)
    product = make_product(source, name="Heat Gun", total_quantity=10, available_quantity=10)

    response = authenticated_client(manager).post(
        f"/api/v1/admin/makerspace/{source.id}/stock-transfers",
        {
            "destination_makerspace_id": dest.id,
            "reason": "Lend to partner space",
            "lines": [{"product_id": product.id, "quantity": 2}],
        },
        format="json",
    )

    assert response.status_code == 403
    product.refresh_from_db()
    assert product.available_quantity == 10  # untouched
    assert StockTransfer.objects.count() == 0


def test_cross_makerspace_transfer_denies_hidden_source_or_destination():
    source = make_space("ops-xfer-hidden-src")
    dest = make_space("ops-xfer-hidden-dst")
    make_member("ops-xfer-hidden-src-manager", source)
    make_member("ops-xfer-hidden-dst-manager", dest)
    source.superadmin_access_enabled = False
    source.save(update_fields=["superadmin_access_enabled"])
    superadmin = make_user("ops-xfer-hidden-super", role=User.Role.SUPERADMIN, access_status=User.AccessStatus.ACTIVE)
    product = make_product(source, name="Hidden Heat Gun", total_quantity=10, available_quantity=10)

    hidden_source = _cross_transfer(superadmin, source, dest, product, 2)
    source.superadmin_access_enabled = True
    source.save(update_fields=["superadmin_access_enabled"])
    dest.superadmin_access_enabled = False
    dest.save(update_fields=["superadmin_access_enabled"])
    hidden_dest = _cross_transfer(superadmin, source, dest, product, 2)

    assert hidden_source.status_code == 403
    assert hidden_dest.status_code == 403
    product.refresh_from_db()
    assert product.available_quantity == 10
    assert InventoryProduct.objects.filter(makerspace=dest, name="Hidden Heat Gun").count() == 0


def test_stocktake_lifecycle_applies_superadmin_adjustment():
    makerspace = make_space("ops-stocktake")
    manager = make_member("ops-stocktake-manager", makerspace, membership_role="inventory_manager", role=User.Role.REQUESTER)
    superadmin = make_user("ops-stocktake-super", role=User.Role.SUPERADMIN, access_status=User.AccessStatus.ACTIVE)
    product = make_product(makerspace, available_quantity=10, total_quantity=10)
    manager_client = authenticated_client(manager)
    super_client = authenticated_client(superadmin)

    created = manager_client.post(
        f"/api/v1/admin/makerspace/{makerspace.id}/stocktakes",
        {"notes": "Cycle count"},
        format="json",
    )
    stocktake_id = created.data["id"]
    counted = manager_client.post(
        f"/api/v1/admin/stocktakes/{stocktake_id}/count-lines",
        {"product_id": product.id, "counted_quantity": 8, "condition": "available"},
        format="json",
    )
    completed = manager_client.post(f"/api/v1/admin/stocktakes/{stocktake_id}/complete")
    approved = super_client.post(f"/api/v1/admin/stocktakes/{stocktake_id}/approve")
    applied = super_client.post(f"/api/v1/admin/stocktakes/{stocktake_id}/apply-adjustments")

    assert created.status_code == 201
    assert counted.status_code == 201
    assert counted.data["variance_quantity"] == -2
    assert completed.status_code == 200
    assert approved.status_code == 200
    assert applied.status_code == 200
    product.refresh_from_db()
    assert product.available_quantity == 8
    assert StocktakeSession.objects.get(pk=stocktake_id).status == StocktakeSession.Status.APPLIED
    assert StocktakeLedgerEntry.objects.filter(stocktake_id=stocktake_id, delta=-2).exists()


def test_stocktake_uses_condition_bucket_as_expected_baseline():
    makerspace = make_space("ops-stocktake-damaged")
    manager = make_member("ops-stocktake-damaged-manager", makerspace, membership_role="inventory_manager", role=User.Role.REQUESTER)
    superadmin = make_user("ops-stocktake-damaged-super", role=User.Role.SUPERADMIN, access_status=User.AccessStatus.ACTIVE)
    product = make_product(makerspace, available_quantity=10, damaged_quantity=2, total_quantity=12)
    manager_client = authenticated_client(manager)
    created = manager_client.post(f"/api/v1/admin/makerspace/{makerspace.id}/stocktakes", {"notes": "Damaged count"}, format="json")

    counted = manager_client.post(
        f"/api/v1/admin/stocktakes/{created.data['id']}/count-lines",
        {"product_id": product.id, "counted_quantity": 2, "condition": "damaged"},
        format="json",
    )
    manager_client.post(f"/api/v1/admin/stocktakes/{created.data['id']}/complete")
    super_client = authenticated_client(superadmin)
    super_client.post(f"/api/v1/admin/stocktakes/{created.data['id']}/approve")
    applied = super_client.post(f"/api/v1/admin/stocktakes/{created.data['id']}/apply-adjustments")

    assert counted.status_code == 201
    assert counted.data["expected_quantity"] == 2
    assert counted.data["variance_quantity"] == 0
    assert applied.status_code == 200
    product.refresh_from_db()
    assert product.damaged_quantity == 2
    assert StocktakeLedgerEntry.objects.filter(stocktake_id=created.data["id"]).count() == 0


def test_stocktake_apply_is_guarded_after_row_lock():
    makerspace = make_space("ops-stocktake-idempotent")
    manager = make_member("ops-stocktake-idempotent-manager", makerspace, membership_role="inventory_manager", role=User.Role.REQUESTER)
    superadmin = make_user("ops-stocktake-idempotent-super", role=User.Role.SUPERADMIN, access_status=User.AccessStatus.ACTIVE)
    product = make_product(makerspace, available_quantity=5, total_quantity=5)
    manager_client = authenticated_client(manager)
    created = manager_client.post(f"/api/v1/admin/makerspace/{makerspace.id}/stocktakes", {"notes": "Apply once"}, format="json")
    manager_client.post(
        f"/api/v1/admin/stocktakes/{created.data['id']}/count-lines",
        {"product_id": product.id, "counted_quantity": 4, "condition": "available"},
        format="json",
    )
    manager_client.post(f"/api/v1/admin/stocktakes/{created.data['id']}/complete")
    super_client = authenticated_client(superadmin)
    super_client.post(f"/api/v1/admin/stocktakes/{created.data['id']}/approve")

    first = super_client.post(f"/api/v1/admin/stocktakes/{created.data['id']}/apply-adjustments")
    second = super_client.post(f"/api/v1/admin/stocktakes/{created.data['id']}/apply-adjustments")

    assert first.status_code == 200
    assert second.status_code == 400
    product.refresh_from_db()
    assert product.available_quantity == 4
    assert InventoryAdjustment.objects.filter(stocktake_id=created.data["id"]).count() == 1


def test_stocktake_asset_status_updates_product_buckets_from_ledger():
    makerspace = make_space("ops-stocktake-asset")
    manager = make_member("ops-stocktake-asset-manager", makerspace, membership_role="inventory_manager", role=User.Role.REQUESTER)
    superadmin = make_user("ops-stocktake-asset-super", role=User.Role.SUPERADMIN, access_status=User.AccessStatus.ACTIVE)
    product = make_product(makerspace, tracking_mode=TrackingMode.INDIVIDUAL, available_quantity=1, total_quantity=1)
    asset = InventoryAsset.objects.create(makerspace=makerspace, product=product, asset_tag="STOCKTAKE-ASSET-1")
    manager_client = authenticated_client(manager)
    created = manager_client.post(f"/api/v1/admin/makerspace/{makerspace.id}/stocktakes", {"notes": "Missing asset"}, format="json")
    manager_client.post(
        f"/api/v1/admin/stocktakes/{created.data['id']}/count-lines",
        {"asset_id": asset.id, "counted_quantity": 0, "condition": "available"},
        format="json",
    )
    manager_client.post(f"/api/v1/admin/stocktakes/{created.data['id']}/complete")
    super_client = authenticated_client(superadmin)
    super_client.post(f"/api/v1/admin/stocktakes/{created.data['id']}/approve")

    applied = super_client.post(f"/api/v1/admin/stocktakes/{created.data['id']}/apply-adjustments")

    assert applied.status_code == 200
    asset.refresh_from_db()
    product.refresh_from_db()
    assert asset.status == InventoryAsset.Status.LOST
    assert (product.available_quantity, product.lost_quantity, product.total_quantity) == (0, 1, 1)
    assert set(StocktakeLedgerEntry.objects.filter(stocktake_id=created.data["id"]).values_list("bucket", "delta")) == {
        ("available", -1),
        ("lost", 1),
    }


def test_superadmin_cannot_approve_or_apply_hidden_makerspace_stocktake():
    makerspace = make_space("ops-stocktake-hidden")
    make_member("ops-stocktake-hidden-manager", makerspace)
    makerspace.superadmin_access_enabled = False
    makerspace.save(update_fields=["superadmin_access_enabled"])
    superadmin = make_user("ops-stocktake-hidden-super", role=User.Role.SUPERADMIN, access_status=User.AccessStatus.ACTIVE)
    stocktake = StocktakeSession.objects.create(
        makerspace=makerspace,
        started_by=superadmin,
        status=StocktakeSession.Status.COMPLETED,
    )
    client = authenticated_client(superadmin)

    approved = client.post(f"/api/v1/admin/stocktakes/{stocktake.id}/approve")
    stocktake.status = StocktakeSession.Status.APPROVED
    stocktake.save(update_fields=["status"])
    applied = client.post(f"/api/v1/admin/stocktakes/{stocktake.id}/apply-adjustments")

    assert approved.status_code == 404
    assert applied.status_code == 404


def test_reports_export_csv_and_xlsx():
    makerspace = make_space("ops-reports")
    manager = make_member("ops-reports-manager", makerspace)
    make_product(
        makerspace,
        name="Meters",
        total_quantity=13,
        available_quantity=10,
        damaged_quantity=1,
        lost_quantity=2,
    )
    client = authenticated_client(manager)

    csv_response = client.get(
        f"/api/v1/admin/makerspace/{makerspace.id}/reports/damaged-missing/export?format=csv"
    )
    xlsx_response = client.get(
        f"/api/v1/admin/makerspace/{makerspace.id}/reports/damaged-missing/export?format=xlsx"
    )

    assert csv_response.status_code == 200
    assert b"damaged_quantity" in csv_response.content
    assert xlsx_response.status_code == 200
    assert xlsx_response["Content-Type"].startswith("application/vnd.openxmlformats")




def test_guest_admin_cannot_view_hardware_reports():
    makerspace = make_space("ops-reports-guest")
    guest = make_handout_member("ops-reports-guest-user", makerspace)
    client = authenticated_client(guest)

    analytics = client.get(f"/api/v1/admin/makerspace/{makerspace.id}/analytics/summary")
    export = client.get(
        f"/api/v1/admin/makerspace/{makerspace.id}/reports/damaged-missing/export"
    )

    assert analytics.status_code == 403
    assert export.status_code == 403


def test_reports_export_prefixes_formula_cells():
    makerspace = make_space("ops-reports-formula")
    manager = make_member("ops-reports-formula-manager", makerspace)
    make_product(
        makerspace,
        name="=HYPERLINK(\"https://evil.test\")",
        available_quantity=9,
        damaged_quantity=1,
        lost_quantity=0,
    )
    client = authenticated_client(manager)

    csv_response = client.get(
        f"/api/v1/admin/makerspace/{makerspace.id}/reports/damaged-missing/export?format=csv"
    )
    xlsx_response = client.get(
        f"/api/v1/admin/makerspace/{makerspace.id}/reports/damaged-missing/export?format=xlsx"
    )

    assert csv_response.status_code == 200
    assert b"'=HYPERLINK" in csv_response.content
    workbook = load_workbook(io.BytesIO(xlsx_response.content))
    assert workbook.active["A2"].value.startswith("'=")


def test_container_history_merges_reviewed_handover_and_qr_scan_events():
    makerspace = make_space("ops-container-history")
    manager = make_member("ops-container-history-manager", makerspace)
    box = make_box(makerspace, "History Bin")
    qr = QrCode.objects.create(
        makerspace=makerspace,
        payload=box.code,
        target_type=QrCode.TargetType.BOX,
        target_id=box.id,
        created_by=manager,
    )
    BoxScan.objects.create(
        makerspace=makerspace,
        box=box,
        request=None,
        actor=manager,
        context=BoxScan.Context.ISSUE,
    )
    QrScanEvent.objects.create(
        makerspace=makerspace,
        qr_code=qr,
        request=None,
        actor=manager,
        context=QrScanEvent.Context.RETURN,
    )

    response = authenticated_client(manager).get(f"/api/v1/admin/containers/{box.id}/history")

    assert response.status_code == 200
    sources = {scan["source"] for scan in response.data["scans"]}
    assert sources == {"box_scan", "qr_scan_event"}
    assert {scan["id"].split(":", 1)[0] for scan in response.data["scans"]} == {"box", "qr"}
    assert {scan["context"] for scan in response.data["scans"]} == {"issue", "return"}


def test_asset_generation_creates_qr_labels_in_print_batch():
    makerspace = make_space("ops-assets")
    manager = make_member("ops-assets-manager", makerspace)
    product = make_product(makerspace, name="Drill", tracking_mode=TrackingMode.INDIVIDUAL)

    client = authenticated_client(manager)
    response = client.post(
        f"/api/v1/admin/products/{product.id}/assets/generate",
        {"count": 2, "create_print_batch": True},
        format="json",
    )

    assert response.status_code == 201
    assert len(response.data["assets"]) == 2
    assert QrCode.objects.filter(target_type=QrCode.TargetType.ASSET).count() == 2
    assert QrPrintBatch.objects.get(pk=response.data["print_batch_id"]).items.count() == 2
    product.refresh_from_db()
    assert product.total_quantity == 2
    assert product.available_quantity == 2
    listing = client.get(f"/api/v1/admin/inventory/{product.id}/assets")
    assert listing.status_code == 200
    assert all(row["qr_code_id"] for row in listing.data["results"])
    assert all(row["qr_payload"] for row in listing.data["results"])


def test_asset_generation_adds_50_unique_sequential_unit_qrs_to_existing_batch():
    makerspace = make_space("ops-assets-50")
    manager = make_member("ops-assets-50-manager", makerspace)
    product = make_product(makerspace, name="Arduino", tracking_mode=TrackingMode.INDIVIDUAL)
    batch = QrPrintBatch.objects.create(makerspace=makerspace, title="Arduino labels", created_by=manager)

    client = authenticated_client(manager)
    response = client.post(
        f"/api/v1/admin/products/{product.id}/assets/generate",
        {"count": 50, "name_prefix": "Arduino", "print_batch_id": batch.id},
        format="json",
    )

    assert response.status_code == 201
    assert len(response.data["assets"]) == 50
    assert InventoryAsset.objects.filter(product=product).count() == 50
    product.refresh_from_db()
    assert product.total_quantity == 50
    assert product.available_quantity == 50
    assert QrCode.objects.filter(target_type=QrCode.TargetType.ASSET).count() == 50
    assert QrCode.objects.filter(target_type=QrCode.TargetType.ASSET).values("payload").distinct().count() == 50
    assert list(batch.items.order_by("sort_order").values_list("label_text", flat=True)) == [
        f"Arduino {number}" for number in range(1, 51)
    ]


def test_asset_generation_fills_existing_units_without_qr_before_creating_new_units():
    makerspace = make_space("ops-assets-missing-qr")
    manager = make_member("ops-assets-missing-qr-manager", makerspace)
    product = make_product(
        makerspace,
        name="Arduino",
        tracking_mode=TrackingMode.INDIVIDUAL,
        total_quantity=3,
        available_quantity=3,
    )
    assets = [
        InventoryAsset.objects.create(makerspace=makerspace, product=product, asset_tag=f"ARD-{number}")
        for number in range(1, 4)
    ]
    QrCode.objects.create(
        makerspace=makerspace,
        target_type=QrCode.TargetType.ASSET,
        target_id=assets[0].id,
        created_by=manager,
    )
    batch = QrPrintBatch.objects.create(makerspace=makerspace, title="Missing unit labels", created_by=manager)

    response = authenticated_client(manager).post(
        f"/api/v1/admin/products/{product.id}/assets/generate",
        {"count": 2, "name_prefix": "Arduino", "print_batch_id": batch.id},
        format="json",
    )

    assert response.status_code == 201
    assert [row["id"] for row in response.data["assets"]] == [assets[1].id, assets[2].id]
    assert InventoryAsset.objects.filter(product=product).count() == 3
    assert QrCode.objects.filter(target_type=QrCode.TargetType.ASSET, target_id__in=[asset.id for asset in assets]).count() == 3
    assert list(batch.items.order_by("sort_order").values_list("label_text", flat=True)) == ["Arduino ARD-2", "Arduino ARD-3"]

def test_qr_batch_accepts_inventory_items_and_rejects_container_qrs():
    makerspace = make_space("ops-qr-batch")
    manager = make_member("ops-qr-batch-manager", makerspace)
    box = make_box(makerspace, "Soldering Bin")
    product = make_product(makerspace, name="Multimeter")
    asset_product = make_product(
        makerspace,
        name="Arduino",
        tracking_mode=TrackingMode.INDIVIDUAL,
        total_quantity=1,
        available_quantity=1,
    )
    asset = InventoryAsset.objects.create(
        makerspace=makerspace,
        product=asset_product,
        asset_tag="ARDUINO-1",
    )
    box_qr = QrCode.objects.create(
        makerspace=makerspace,
        payload=box.code,
        target_type=QrCode.TargetType.BOX,
        target_id=box.id,
        created_by=manager,
    )
    product_qr = QrCode.objects.create(
        makerspace=makerspace,
        target_type=QrCode.TargetType.PRODUCT,
        target_id=product.id,
        created_by=manager,
    )
    asset_qr = QrCode.objects.create(
        makerspace=makerspace,
        target_type=QrCode.TargetType.ASSET,
        target_id=asset.id,
        created_by=manager,
    )
    client = authenticated_client(manager)
    batch_response = client.post(
        f"/api/v1/admin/makerspace/{makerspace.id}/qr-print-batches",
        {"title": "Bench labels"},
        format="json",
    )
    batch_id = batch_response.data["id"]

    box_item = client.post(
        f"/api/v1/admin/qr-print-batches/{batch_id}/items",
        {"qr_code_id": box_qr.id, "label_text": box.label},
        format="json",
    )
    product_item = client.post(
        f"/api/v1/admin/qr-print-batches/{batch_id}/items",
        {"qr_code_id": product_qr.id, "label_text": product.name},
        format="json",
    )
    asset_item = client.post(
        f"/api/v1/admin/qr-print-batches/{batch_id}/items",
        {"qr_code_id": asset_qr.id, "label_text": asset.asset_tag},
        format="json",
    )
    downloaded = client.get(f"/api/v1/admin/qr-print-batches/{batch_id}/download")

    assert batch_response.status_code == 201
    assert box_item.status_code == 400
    assert product_item.status_code == 201
    assert asset_item.status_code == 201
    assert downloaded.status_code == 200
    assert downloaded["Content-Type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(downloaded.content)) as archive:
        assert len(archive.namelist()) == 2
        svg_contents = "".join(archive.read(name).decode("utf-8") for name in archive.namelist())
    assert "Soldering Bin" not in svg_contents
    assert "Multimeter" in svg_contents
    assert "ARDUINO-1" in svg_contents


def test_qr_batch_replaces_duplicate_inventory_qr_item():
    makerspace = make_space("ops-qr-batch-replace")
    manager = make_member("ops-qr-batch-replace-manager", makerspace)
    product = make_product(makerspace, name="Multimeter")
    qr = QrCode.objects.create(
        makerspace=makerspace,
        target_type=QrCode.TargetType.PRODUCT,
        target_id=product.id,
        created_by=manager,
    )
    batch = QrPrintBatch.objects.create(makerspace=makerspace, title="Bench labels", created_by=manager)
    client = authenticated_client(manager)

    first = client.post(
        f"/api/v1/admin/qr-print-batches/{batch.id}/items",
        {"qr_code_id": qr.id, "label_text": "Old label"},
        format="json",
    )
    second = client.post(
        f"/api/v1/admin/qr-print-batches/{batch.id}/items",
        {"qr_code_id": qr.id, "label_text": "New label"},
        format="json",
    )

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.data["id"] == second.data["id"]
    assert QrPrintBatchItem.objects.filter(batch=batch, qr_code=qr).count() == 1
    item = QrPrintBatchItem.objects.get(batch=batch, qr_code=qr)
    assert item.label_text == "New label"

def test_asset_qr_reprint_returns_existing_active_qr():
    makerspace = make_space("ops-asset-qr-reprint")
    manager = make_member("ops-asset-qr-reprint-manager", makerspace)
    product = make_product(makerspace, tracking_mode=TrackingMode.INDIVIDUAL)
    asset = InventoryAsset.objects.create(makerspace=makerspace, product=product, asset_tag="ARD-LOST-LABEL")
    existing = QrCode.objects.create(
        makerspace=makerspace,
        target_type=QrCode.TargetType.ASSET,
        target_id=asset.id,
        created_by=manager,
    )

    response = authenticated_client(manager).post(
        f"/api/v1/admin/assets/{asset.id}/qr",
        {},
        format="json",
    )

    assert response.status_code == 201
    assert response.data["id"] == existing.id
    assert response.data["payload"] == existing.payload
    assert QrCode.objects.filter(target_type=QrCode.TargetType.ASSET, target_id=asset.id).count() == 1

def test_product_qr_creation_rejects_individual_tracked_inventory():
    makerspace = make_space("ops-product-qr-individual")
    manager = make_member("ops-product-qr-individual-manager", makerspace)
    product = make_product(makerspace, tracking_mode=TrackingMode.INDIVIDUAL)

    response = authenticated_client(manager).post(
        "/api/v1/admin/qr/tools",
        {"makerspace_id": makerspace.id, "product_id": product.id},
        format="json",
    )

    assert response.status_code == 400
    assert "unit QR" in str(response.data)
    assert not QrCode.objects.filter(target_type=QrCode.TargetType.PRODUCT, target_id=product.id).exists()

def test_qr_batch_items_enforce_manage_qr_rbac_and_makerspace_scope():
    space_a = make_space("ops-qr-scope-a")
    space_b = make_space("ops-qr-scope-b")
    manager_a = make_member("ops-qr-scope-manager-a", space_a)
    guest_a = make_handout_member("ops-qr-scope-guest-a", space_a)
    box_b = make_box(space_b, "Foreign Bin")
    qr_b = QrCode.objects.create(
        makerspace=space_b,
        payload=box_b.code,
        target_type=QrCode.TargetType.BOX,
        target_id=box_b.id,
    )
    batch_b = QrPrintBatch.objects.create(makerspace=space_b, title="Foreign labels")

    denied_role = authenticated_client(guest_a).post(
        f"/api/v1/admin/makerspace/{space_a.id}/qr-print-batches",
        {"title": "Denied"},
        format="json",
    )
    denied_scope = authenticated_client(manager_a).post(
        f"/api/v1/admin/qr-print-batches/{batch_b.id}/items",
        {"qr_code_id": qr_b.id},
        format="json",
    )

    assert denied_role.status_code == 403
    assert denied_scope.status_code == 404


def test_intra_makerspace_asset_status_transfer_updates_product_buckets():
    makerspace = make_space("ops-transfer-asset-status")
    manager = make_member("ops-transfer-asset-status-manager", makerspace)
    source = make_box(makerspace, "Asset Source")
    destination = make_box(makerspace, "Asset Destination")
    product = make_product(
        makerspace,
        name="Serialized Scope",
        box=source,
        tracking_mode=TrackingMode.INDIVIDUAL,
        total_quantity=1,
        available_quantity=1,
    )
    asset = InventoryAsset.objects.create(
        makerspace=makerspace,
        product=product,
        box=source,
        asset_tag="SCOPE-001",
        status=InventoryAsset.Status.AVAILABLE,
    )

    response = authenticated_client(manager).post(
        f"/api/v1/admin/makerspace/{makerspace.id}/stock-transfers",
        {
            "source_container_id": source.id,
            "destination_container_id": destination.id,
            "reason": "Move damaged unit to repair shelf",
            "lines": [
                {
                    "asset_id": asset.id,
                    "from_status": InventoryAsset.Status.AVAILABLE,
                    "to_status": InventoryAsset.Status.DAMAGED,
                }
            ],
        },
        format="json",
    )

    assert response.status_code == 201
    asset.refresh_from_db()
    product.refresh_from_db()
    assert (asset.box_id, asset.status) == (destination.id, InventoryAsset.Status.DAMAGED)
    assert (product.available_quantity, product.damaged_quantity, product.total_quantity) == (0, 1, 1)


def test_destination_manager_can_retrieve_incoming_stock_transfer():
    source = make_space("ops-transfer-detail-src")
    dest = make_space("ops-transfer-detail-dst")
    superadmin = make_user(
        "ops-transfer-detail-super",
        role=User.Role.SUPERADMIN,
        access_status=User.AccessStatus.ACTIVE,
    )
    dest_manager = make_member("ops-transfer-detail-dest-manager", dest)
    product = make_product(source, name="Bench Supply", total_quantity=5, available_quantity=5)
    created = _cross_transfer(superadmin, source, dest, product, 2)
    transfer_id = created.data["id"]

    list_response = authenticated_client(dest_manager).get(
        f"/api/v1/admin/makerspace/{dest.id}/stock-transfers",
    )
    detail_response = authenticated_client(dest_manager).get(
        f"/api/v1/admin/stock-transfers/{transfer_id}",
    )

    rows = list_response.data.get("results", list_response.data)
    assert created.status_code == 201
    assert list_response.status_code == 200
    assert [row["id"] for row in rows] == [transfer_id]
    assert detail_response.status_code == 200
    assert detail_response.data["id"] == transfer_id
