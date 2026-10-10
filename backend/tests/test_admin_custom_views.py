import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.inventory.models import InventoryProduct, PublicAvailabilityMode, TrackingMode
from apps.operations.models import StockTransfer, StocktakeLine, StocktakeSession
from tests.return_helpers import make_box, make_product, make_space, make_user
from tests.accounts.mfa_helpers import force_mfa_login

pytestmark = pytest.mark.django_db


def make_superadmin(username="admin-custom-super"):
    return make_user(
        username,
        role=User.Role.SUPERADMIN,
        access_status=User.AccessStatus.ACTIVE,
        is_staff=True,
        is_superuser=True,
    )


def admin_client(user=None):
    client = Client()
    force_mfa_login(client, user or make_superadmin())
    return client


def test_stock_transfer_admin_add_intra_cross_and_hidden_guard():
    user = make_superadmin("admin-transfer-super")
    source = make_space("admin-transfer-source")
    dest = make_space("admin-transfer-dest")
    hidden = make_space("admin-transfer-hidden")
    hidden.superadmin_access_enabled = False
    hidden.save(update_fields=["superadmin_access_enabled"])
    source_box = make_box(source, "Source shelf")
    dest_box = make_box(source, "Dest shelf")
    product = make_product(
        source,
        name="PLA",
        box=source_box,
        total_quantity=5,
        available_quantity=5,
    )
    client = admin_client(user)
    url = reverse("admin:operations_stocktransfer_add")

    response = client.post(
        url,
        {
            "source_makerspace": source.id,
            "source_container": source_box.id,
            "destination_container": dest_box.id,
            "product": product.id,
            "quantity": "5",
            "reason": "Move shelf",
        },
    )

    assert response.status_code == 302
    product.refresh_from_db()
    assert product.box_id == dest_box.id
    assert StockTransfer.objects.count() == 1

    product.box = None
    product.available_quantity = 5
    product.total_quantity = 5
    product.save(update_fields=["box", "available_quantity", "total_quantity", "updated_at"])
    response = client.post(
        url,
        {
            "source_makerspace": source.id,
            "destination_makerspace": dest.id,
            "product": product.id,
            "quantity": "2",
            "reason": "Share stock",
        },
    )

    assert response.status_code == 302
    product.refresh_from_db()
    assert product.available_quantity == 3
    assert InventoryProduct.objects.get(makerspace=dest, name="PLA").available_quantity == 2
    assert StockTransfer.objects.count() == 2
    assert AuditLog.objects.filter(action="stock_transfer.applied").count() == 2

    response = client.post(
        url,
        {
            "source_makerspace": hidden.id,
            "product": product.id,
            "quantity": "1",
            "reason": "Hidden",
        },
    )

    assert response.status_code == 200
    assert StockTransfer.objects.count() == 2


def test_stock_transfer_admin_rejects_cross_individual_product():
    source = make_space("admin-transfer-ind-source")
    dest = make_space("admin-transfer-ind-dest")
    product = make_product(
        source,
        tracking_mode=TrackingMode.INDIVIDUAL,
        total_quantity=1,
        available_quantity=1,
    )

    response = admin_client(make_superadmin("admin-transfer-ind-super")).post(
        reverse("admin:operations_stocktransfer_add"),
        {
            "source_makerspace": source.id,
            "destination_makerspace": dest.id,
            "product": product.id,
            "quantity": "1",
            "reason": "Cross",
        },
    )

    assert response.status_code == 200
    assert not StockTransfer.objects.exists()


def test_stocktake_count_admin_uses_service_and_blocks_non_countable():
    user = make_superadmin("admin-stocktake-count-super")
    space = make_space("admin-stocktake-count")
    product = make_product(space, total_quantity=4, available_quantity=4)
    stocktake = StocktakeSession.objects.create(makerspace=space, started_by=user)
    client = admin_client(user)

    response = client.post(
        reverse("admin:operations_stocktakesession_count", args=[stocktake.pk]),
        {
            "product": product.id,
            "counted_quantity": "3",
            "condition": StocktakeLine.Condition.AVAILABLE,
            "notes": "One missing",
        },
    )

    assert response.status_code == 302
    line = StocktakeLine.objects.get(stocktake=stocktake)
    assert line.expected_quantity == 4
    assert line.counted_quantity == 3
    assert AuditLog.objects.filter(action="stocktake.line_counted").exists()

    stocktake.status = StocktakeSession.Status.COMPLETED
    stocktake.save(update_fields=["status"])
    response = client.post(
        reverse("admin:operations_stocktakesession_count", args=[stocktake.pk]),
        {
            "product": product.id,
            "counted_quantity": "2",
            "condition": StocktakeLine.Condition.AVAILABLE,
        },
    )

    assert response.status_code == 302
    assert StocktakeLine.objects.filter(stocktake=stocktake).count() == 1


def test_inventory_bulk_import_admin_preview_apply_and_parse_error():
    user = make_superadmin("admin-bulk-import-super")
    space = make_space("admin-bulk-import")
    client = admin_client(user)
    url = reverse("admin:inventory_inventoryproduct_bulk_import")
    upload = SimpleUploadedFile(
        "items.csv",
        b"name,total_quantity,available_quantity\nCalipers,2,2\n",
        content_type="text/csv",
    )

    preview = client.post(url, {"makerspace": space.id, "file": upload})
    apply = client.post(url, {"apply": "1"})

    assert preview.status_code == 200
    assert apply.status_code == 302
    assert InventoryProduct.objects.filter(makerspace=space, name="Calipers").exists()
    assert AuditLog.objects.filter(action="inventory.bulk_imported").exists()

    bad = client.post(
        url,
        {
            "makerspace": space.id,
            "file": SimpleUploadedFile("bad.json", b"not-json", content_type="application/json"),
        },
    )

    assert bad.status_code == 200
