"""Control-panel image validation, replacement and cleanup."""

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.audit.models import AuditLog
from apps.inventory.models import PublicAvailabilityMode
from tests.return_helpers import make_product, make_space
from tests.test_admin_custom_views import admin_client, make_superadmin

pytestmark = pytest.mark.django_db


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
        "reorder_point": product.reorder_point,
        "reorder_quantity": product.reorder_quantity,
        "kit_components": "[]",
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
            "public_site_enabled": "on" if space.public_site_enabled else "",
            "public_landing_page": space.public_landing_page,
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
