import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.inventory.models import InventoryProduct, PublicAvailabilityMode, TrackingMode
from apps.operations.models import StockTransfer, StocktakeLine, StocktakeSession
from tests.return_helpers import make_box, make_product, make_space, make_user

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
    client.force_login(user or make_superadmin())
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


def _product_admin_payload(product, **extra):
    data = {
        "makerspace": product.makerspace_id,
        "box": product.box_id or "",
        "category": product.category_id or "",
        "name": product.name,
        "description": product.description,
        "image_key": product.image_key,
        "tracking_mode": product.tracking_mode,
        "total_quantity": product.total_quantity,
        "available_quantity": product.available_quantity,
        "reserved_quantity": product.reserved_quantity,
        "issued_quantity": product.issued_quantity,
        "damaged_quantity": product.damaged_quantity,
        "lost_quantity": product.lost_quantity,
        "needs_fix_quantity": product.needs_fix_quantity,
        "is_public": "on",
        "public_availability_mode": product.public_availability_mode,
        "storage_location": product.storage_location,
    }
    data.update(extra)
    return data


def test_admin_product_image_upload_validates_and_deletes_old_after_save(
    monkeypatch, settings, django_capture_on_commit_callbacks
):
    settings.PUBLIC_IMAGE_MAX_BYTES = 5
    space = make_space("admin-image-product")
    product = make_product(
        space,
        image_key=f"items/{space.id}/old.png",
        public_availability_mode=PublicAvailabilityMode.STATUS_ONLY,
    )
    events = []
    uploaded = {}

    def put_bytes(key, data, content_type):
        uploaded["key"] = key
        events.append(("put", key, data, content_type))

    def delete_object(key):
        product.refresh_from_db()
        assert product.image_key == uploaded["key"]
        events.append(("delete", key))

    monkeypatch.setattr("apps.inventory.public_image_storage.put_bytes", put_bytes)
    monkeypatch.setattr("apps.inventory.public_image_storage.delete_object", delete_object)

    # The replaced object is now deleted on_commit rather than inline, so a rollback can
    # never destroy a file whose row came back. The ordering this test exists for still
    # holds -- and holds more strongly: the delete now cannot precede the commit.
    with django_capture_on_commit_callbacks(execute=True):
        response = admin_client(make_superadmin("admin-image-product-super")).post(
            reverse("admin:inventory_inventoryproduct_change", args=[product.pk]),
            _product_admin_payload(
                product,
                image_upload=SimpleUploadedFile("new.png", b"abc", content_type="image/png"),
                _save="Save",
            ),
        )

    assert response.status_code == 302
    product.refresh_from_db()
    assert product.image_key == uploaded["key"]
    assert events[0][0] == "put"
    assert events[1] == ("delete", f"items/{space.id}/old.png")
    assert AuditLog.objects.filter(action="inventory.image_attached").exists()

    response = admin_client(make_superadmin("admin-image-size-super")).post(
        reverse("admin:inventory_inventoryproduct_change", args=[product.pk]),
        _product_admin_payload(
            product,
            image_upload=SimpleUploadedFile("huge.png", b"too-large", content_type="image/png"),
            _save="Save",
        ),
    )

    assert response.status_code == 200
    assert events == events[:2]

    response = admin_client(make_superadmin("admin-image-mime-super")).post(
        reverse("admin:inventory_inventoryproduct_change", args=[product.pk]),
        _product_admin_payload(
            product,
            image_upload=SimpleUploadedFile("bad.jpg", b"abc", content_type="image/png"),
            _save="Save",
        ),
    )

    assert response.status_code == 200
    assert events == events[:2]


def test_admin_image_clear(monkeypatch, django_capture_on_commit_callbacks):
    deleted = []
    stored = []
    monkeypatch.setattr(
        "apps.inventory.public_image_storage.put_bytes",
        lambda key, data, content_type: stored.append((key, data, content_type)),
    )
    monkeypatch.setattr(
        "apps.inventory.public_image_storage.delete_object",
        lambda key: deleted.append(key),
    )
    space = make_space("admin-image-clear")
    product = make_product(space, image_key=f"items/{space.id}/old.png")
    client = admin_client(make_superadmin("admin-image-clear-super"))

    # Cleared objects are deleted on_commit now, so the callbacks must run to observe it.
    with django_capture_on_commit_callbacks(execute=True):
        clear = client.post(
            reverse("admin:inventory_inventoryproduct_change", args=[product.pk]),
            _product_admin_payload(product, clear_image="on", _save="Save"),
        )
    assert clear.status_code == 302
    product.refresh_from_db()
    assert product.image_key == ""
    assert deleted == [f"items/{space.id}/old.png"]
    assert AuditLog.objects.filter(action="inventory.image_cleared").exists()


def test_admin_makerspace_logo_and_cover_upload(monkeypatch):
    stored = []
    monkeypatch.setattr(
        "apps.inventory.public_image_storage.put_bytes",
        lambda key, data, content_type: stored.append((key, data, content_type)),
    )
    monkeypatch.setattr("apps.inventory.public_image_storage.delete_object", lambda key: None)
    space = make_space("admin-image-makerspace")

    response = admin_client(make_superadmin("admin-image-makerspace-super")).post(
        reverse("admin:makerspaces_makerspace_change", args=[space.pk]),
        {
            "name": space.name,
            "public_code": space.public_code,
            "slug": space.slug,
            "location": space.location,
            "public_inventory_enabled": "on",
            "frontend_domain": space.frontend_domain or "",
            "default_loan_days": space.default_loan_days,
            "logo_upload": SimpleUploadedFile("logo.png", b"abc", content_type="image/png"),
            "cover_upload": SimpleUploadedFile("cover.jpg", b"abc", content_type="image/jpeg"),
            "memberships-TOTAL_FORMS": "0",
            "memberships-INITIAL_FORMS": "0",
            "memberships-MIN_NUM_FORMS": "0",
            "memberships-MAX_NUM_FORMS": "1000",
            "_save": "Save",
        },
    )

    assert response.status_code == 302
    space.refresh_from_db()
    assert space.logo_key == stored[0][0]
    assert space.cover_image_key == stored[1][0]
    assert AuditLog.objects.filter(action="makerspace.logo_attached").exists()
    assert AuditLog.objects.filter(action="makerspace.cover_attached").exists()
