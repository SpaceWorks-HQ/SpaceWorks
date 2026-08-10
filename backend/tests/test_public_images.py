from unittest.mock import Mock

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.audit.models import AuditLog
from apps.inventory.models import InventoryProduct
from apps.makerspaces import lifecycle
from tests.return_helpers import authenticated_client, make_member, make_product, make_space, make_user

pytestmark = pytest.mark.django_db


def image_url(product):
    return reverse("admin-inventory-image", kwargs={"pk": product.id})


def logo_url(makerspace):
    return reverse("admin-makerspace-logo", kwargs={"makerspace_id": makerspace.id})


def cover_url(makerspace):
    return reverse("admin-makerspace-cover", kwargs={"makerspace_id": makerspace.id})


def mock_public_storage(monkeypatch, *, size=123):
    from apps.inventory import public_image_storage

    monkeypatch.setattr(
        "apps.inventory.public_image_storage.presigned_upload",
        lambda object_key, content_type: {
            "url": "http://minio/public-upload",
            "fields": {"key": object_key, "Content-Type": content_type},
        },
    )
    monkeypatch.setattr(
        "apps.inventory.public_image_storage.finalize_upload",
        lambda object_key: public_image_storage._finalize_result(object_key, size),
    )
    monkeypatch.setattr("apps.inventory.public_image_storage.sniff_is_valid_image", lambda object_key: True)
    delete = Mock()
    monkeypatch.setattr("apps.inventory.public_image_storage.delete_object", delete)
    return delete


def test_inventory_image_upload_attach_and_public_serializer(monkeypatch, settings):
    settings.PUBLIC_IMAGE_BASE_URL = "http://cdn.test/public-images"
    delete = mock_public_storage(monkeypatch)
    makerspace = make_space("public-image-item")
    user = make_member("public-image-item-user", makerspace)
    product = make_product(makerspace, name="Laser Cutter")
    client = authenticated_client(user)

    upload = client.post(
        image_url(product),
        {"content_type": "image/png", "filename": "laser.png"},
        format="json",
    )
    object_key = upload.data["object_key"]
    attached = client.put(image_url(product), {"object_key": object_key}, format="json")
    public = APIClient().get(reverse("public-inventory", kwargs={"makerspace_slug": makerspace.slug}))

    assert upload.status_code == 201
    assert object_key.startswith(f"items/{makerspace.id}/")
    assert upload.data["url"] == "http://minio/public-upload"
    assert attached.status_code == 200
    assert attached.data["image_key"] == object_key
    assert attached.data["image_url"] == f"http://cdn.test/public-images/{object_key}"
    product.refresh_from_db()
    assert product.image_key == object_key
    assert public.status_code == 200
    assert public.data["results"][0]["image_url"] == f"http://cdn.test/public-images/{object_key}"
    assert AuditLog.objects.filter(action="inventory.image_attached").exists()
    delete.assert_not_called()


@pytest.mark.parametrize(
    "payload",
    [
        {"content_type": "image/svg+xml", "filename": "logo.svg"},
        {"content_type": "image/png", "filename": "logo.jpg"},
    ],
)
def test_inventory_image_rejects_bad_mime_or_extension(monkeypatch, payload):
    monkeypatch.setattr(
        "apps.inventory.public_image_storage.presigned_upload",
        lambda object_key, content_type: pytest.fail("storage should not be called"),
    )
    makerspace = make_space("public-image-bad")
    user = make_member("public-image-bad-user", makerspace)
    product = make_product(makerspace)

    response = authenticated_client(user).post(image_url(product), payload, format="json")

    assert response.status_code == 400
    assert AuditLog.objects.count() == 0


def test_inventory_image_rejects_cross_makerspace_object_key(monkeypatch):
    mock_public_storage(monkeypatch)
    makerspace = make_space("public-image-prefix")
    user = make_member("public-image-prefix-user", makerspace)
    product = make_product(makerspace)

    response = authenticated_client(user).put(
        image_url(product),
        {"object_key": "items/999/not-yours.png"},
        format="json",
    )

    assert response.status_code == 400
    product.refresh_from_db()
    assert product.image_key == ""
    assert AuditLog.objects.count() == 0


def test_inventory_image_post_supports_put_presign_mode(monkeypatch, settings):
    settings.STORAGE_PRESIGN_METHOD = "put"
    settings.PUBLIC_IMAGE_BUCKET = "catalog-public"
    settings.PUBLIC_IMAGE_URL_TTL_SECONDS = 99
    makerspace = make_space("public-image-put-mode")
    user = make_member("public-image-put-mode-user", makerspace)
    product = make_product(makerspace)

    class FakePublicClient:
        def generate_presigned_url(self, operation, Params, ExpiresIn):
            assert operation == "put_object"
            assert Params["Bucket"] == "catalog-public"
            assert Params["Key"].startswith(f"staging/items/{makerspace.id}/")
            assert Params["ContentType"] == "image/jpeg"
            assert ExpiresIn == 99
            return "http://minio/public-put"

    monkeypatch.setattr("apps.inventory.public_image_storage._public_client", lambda: FakePublicClient())

    response = authenticated_client(user).post(
        image_url(product),
        {"content_type": "image/jpeg", "filename": "photo.jpeg"},
        format="json",
    )

    assert response.status_code == 201
    assert response.data["method"] == "PUT"
    assert response.data["headers"] == {"Content-Type": "image/jpeg"}
    assert response.data["url"] == "http://minio/public-put"


def test_inventory_image_attach_rejects_invalid_final_size(monkeypatch):
    mock_public_storage(monkeypatch, size=0)
    makerspace = make_space("public-image-size")
    user = make_member("public-image-size-user", makerspace)
    product = make_product(makerspace)

    response = authenticated_client(user).put(
        image_url(product), {"object_key": f"items/{makerspace.id}/empty.png"}, format="json"
    )

    assert response.status_code == 400
    product.refresh_from_db()
    assert product.image_key == ""
    assert AuditLog.objects.count() == 0


def test_inventory_image_cross_tenant_product_is_not_found(monkeypatch):
    mock_public_storage(monkeypatch)
    own_space = make_space("public-image-own")
    other_space = make_space("public-image-other")
    user = make_member("public-image-own-user", own_space)
    other_product = make_product(other_space)

    response = authenticated_client(user).post(
        image_url(other_product),
        {"content_type": "image/png", "filename": "other.png"},
        format="json",
    )

    assert response.status_code == 404


def test_inventory_image_delete_clears_key_and_audits(
    monkeypatch, django_capture_on_commit_callbacks
):
    delete = mock_public_storage(monkeypatch)
    makerspace = make_space("public-image-delete")
    user = make_member("public-image-delete-user", makerspace)
    product = make_product(makerspace, image_key=f"items/{makerspace.id}/old.png")

    # Retiring the object is deferred to on_commit so a rollback can never destroy a file
    # whose row came back, and the quota is freed only once the delete is confirmed.
    with django_capture_on_commit_callbacks(execute=True):
        response = authenticated_client(user).delete(image_url(product))

    assert response.status_code == 200
    assert response.data["image_key"] == ""
    product.refresh_from_db()
    assert product.image_key == ""
    delete.assert_called_once_with(f"items/{makerspace.id}/old.png")
    assert AuditLog.objects.filter(action="inventory.image_cleared").exists()


def test_makerspace_logo_and_cover_upload_attach(monkeypatch, settings):
    settings.PUBLIC_IMAGE_BASE_URL = "http://cdn.test/public-images"
    mock_public_storage(monkeypatch)
    makerspace = make_space("public-image-brand")
    user = make_member("public-image-brand-user", makerspace)
    client = authenticated_client(user)

    logo_upload = client.post(
        logo_url(makerspace),
        {"content_type": "image/webp", "filename": "logo.webp"},
        format="json",
    )
    cover_upload = client.post(
        cover_url(makerspace),
        {"content_type": "image/jpeg", "filename": "cover.jpg"},
        format="json",
    )
    logo_attach = client.put(
        logo_url(makerspace),
        {"object_key": logo_upload.data["object_key"]},
        format="json",
    )
    cover_attach = client.put(
        cover_url(makerspace),
        {"object_key": cover_upload.data["object_key"]},
        format="json",
    )
    directory = APIClient().get(reverse("public-makerspaces"))

    assert logo_upload.status_code == 201
    assert cover_upload.status_code == 201
    assert logo_attach.status_code == 200
    assert cover_attach.status_code == 200
    makerspace.refresh_from_db()
    assert makerspace.logo_key == logo_upload.data["object_key"]
    assert makerspace.cover_image_key == cover_upload.data["object_key"]
    assert directory.status_code == 200
    row = directory.data[0]
    assert row["logo_url"] == f"http://cdn.test/public-images/{makerspace.logo_key}"
    assert row["cover_image_url"] == f"http://cdn.test/public-images/{makerspace.cover_image_key}"
    assert AuditLog.objects.filter(action="makerspace.logo_attached").exists()
    assert AuditLog.objects.filter(action="makerspace.cover_attached").exists()


def test_makerspace_image_cross_tenant_manager_is_not_found(monkeypatch):
    mock_public_storage(monkeypatch)
    own_space = make_space("public-image-space-own")
    other_space = make_space("public-image-space-other")
    user = make_member("public-image-space-user", own_space)

    response = authenticated_client(user).post(
        logo_url(other_space),
        {"content_type": "image/png", "filename": "logo.png"},
        format="json",
    )

    assert response.status_code == 404


def test_makerspace_logo_delete_clears_key(
    monkeypatch, django_capture_on_commit_callbacks
):
    delete = mock_public_storage(monkeypatch)
    makerspace = make_space("public-image-logo-delete")
    makerspace.logo_key = f"makerspace/{makerspace.id}/old.png"
    makerspace.save(update_fields=["logo_key"])
    user = make_member("public-image-logo-delete-user", makerspace)

    with django_capture_on_commit_callbacks(execute=True):
        response = authenticated_client(user).delete(logo_url(makerspace))

    assert response.status_code == 200
    makerspace.refresh_from_db()
    assert makerspace.logo_key == ""
    delete.assert_called_once_with(f"makerspace/{makerspace.id}/old.png")
    assert AuditLog.objects.filter(action="makerspace.logo_cleared").exists()


@pytest.mark.django_db(transaction=True)
def test_purge_deletes_public_image_keys(monkeypatch):
    actor = make_user(
        "public-image-purge-super",
        role="superadmin",
        access_status="active",
        is_staff=True,
        is_superuser=True,
    )
    makerspace = make_space("public-image-purge")
    product = make_product(makerspace, image_key=f"items/{makerspace.id}/product.png")
    makerspace.logo_key = f"makerspace/{makerspace.id}/logo.png"
    makerspace.cover_image_key = f"makerspace/{makerspace.id}/cover.png"
    makerspace.save(update_fields=["logo_key", "cover_image_key"])
    deleted = []
    monkeypatch.setattr(lifecycle, "_delete_storage_keys", lambda keys: None)
    monkeypatch.setattr(
        "apps.inventory.public_image_storage.delete_object",
        lambda key: deleted.append(key),
    )

    archived = lifecycle.archive(makerspace, actor)
    lifecycle.purge(archived, actor)

    assert set(deleted) == {
        product.image_key,
        f"makerspace/{makerspace.id}/logo.png",
        f"makerspace/{makerspace.id}/cover.png",
    }
    assert InventoryProduct.objects.filter(pk=product.pk).count() == 0
