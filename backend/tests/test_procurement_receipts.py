from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from django.urls import reverse
from rest_framework.exceptions import ValidationError

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.makerspaces.models import MakerspaceMembership
from apps.procurement.models import ToBuyItem, ToBuyReceipt
from tests.return_helpers import authenticated_client, make_member, make_print_manager, make_space
from tests.test_procurement import make_inventory_manager, make_space_manager
from tests.handout_roles import make_handout_member

pytestmark = pytest.mark.django_db


def detail_url(item):
    return f"/api/v1/procurement/to-buy/{item.id}"


def receipt_presign_url(item):
    return f"/api/v1/procurement/to-buy/{item.id}/receipts/presign"


def receipt_list_url(item):
    return f"/api/v1/procurement/to-buy/{item.id}/receipts"


def receipt_url(receipt):
    return f"/api/v1/procurement/to-buy/receipts/{receipt.id}/url"


def receipt_detail_url(receipt):
    return f"/api/v1/procurement/to-buy/receipts/{receipt.id}"


def mock_receipt_storage(monkeypatch, *, size=123, content_type="application/pdf"):
    monkeypatch.setattr(
        "apps.procurement.storage.presigned_upload",
        lambda object_key, content_type: {
            "url": "http://minio/procurement",
            "fields": {"key": object_key, "Content-Type": content_type},
        },
    )
    monkeypatch.setattr(
        "apps.procurement.storage.finalize_receipt_upload",
        lambda item, object_key: SimpleNamespace(size=size, content_type=content_type),
    )
    monkeypatch.setattr("apps.procurement.storage.presigned_get_url", lambda object_key: "https://signed-receipt")
    delete = Mock()
    monkeypatch.setattr("apps.procurement.storage.delete_object", delete)
    return delete


def test_receipt_presign_finalize_list_signed_url_delete(monkeypatch):
    delete = mock_receipt_storage(monkeypatch)
    makerspace = make_space("proc-receipts")
    manager = make_inventory_manager("proc-receipts-manager", makerspace)
    item = ToBuyItem.objects.create(makerspace=makerspace, kind=ToBuyItem.Kind.HARDWARE, name="Crimp tool")
    client = authenticated_client(manager)

    presign = client.post(
        receipt_presign_url(item),
        {"filename": "receipt.pdf", "content_type": "application/pdf"},
        format="json",
    )
    object_key = presign.data["object_key"]
    finalized = client.post(receipt_list_url(item), {"object_key": object_key}, format="json")
    receipt = ToBuyReceipt.objects.get()
    listed = client.get(receipt_list_url(item))
    signed = client.get(receipt_url(receipt))
    duplicate = client.post(receipt_list_url(item), {"object_key": object_key}, format="json")
    deleted = client.delete(receipt_detail_url(receipt))

    assert presign.status_code == 201
    assert object_key.startswith(f"procurement/{makerspace.id}/")
    assert presign.data["upload"]["url"] == "http://minio/procurement"
    assert finalized.status_code == 201
    assert finalized.data["uploaded_by"] == manager.id
    assert finalized.data["uploaded_by_username"] == manager.username
    assert "object_key" not in finalized.data
    assert listed.status_code == 200
    assert listed.data[0]["id"] == receipt.id
    assert "object_key" not in listed.data[0]
    assert signed.status_code == 200
    assert signed.data == {"url": "https://signed-receipt"}
    assert duplicate.status_code == 400
    assert deleted.status_code == 204
    assert not ToBuyReceipt.objects.filter(pk=receipt.pk).exists()
    delete.assert_called_once_with(object_key)
    assert list(AuditLog.objects.order_by("id").values_list("action", flat=True)) == [
        "procurement.receipt_added",
        "procurement.receipt_removed",
    ]


def test_receipt_cross_tenant_and_stream_rbac(monkeypatch):
    mock_receipt_storage(monkeypatch)
    makerspace = make_space("proc-receipt-rbac")
    other_space = make_space("proc-receipt-rbac-other")
    hardware_item = ToBuyItem.objects.create(makerspace=makerspace, kind=ToBuyItem.Kind.HARDWARE, name="Hardware")
    printing_item = ToBuyItem.objects.create(makerspace=makerspace, kind=ToBuyItem.Kind.PRINTING, name="Printing")
    receipt = ToBuyReceipt.objects.create(to_buy_item=hardware_item, object_key=f"procurement/{makerspace.id}/receipt.pdf")
    inventory_manager = make_inventory_manager("proc-receipt-inv", makerspace)
    print_manager = make_print_manager("proc-receipt-print", makerspace)
    other_member = make_member("proc-receipt-other", other_space)
    guest_admin = make_handout_member("proc-receipt-guest", makerspace)

    assert authenticated_client(print_manager).post(receipt_presign_url(hardware_item), {"filename": "r.pdf", "content_type": "application/pdf"}, format="json").status_code == 404
    assert authenticated_client(inventory_manager).post(receipt_presign_url(printing_item), {"filename": "r.pdf", "content_type": "application/pdf"}, format="json").status_code == 404
    assert authenticated_client(other_member).get(receipt_url(receipt)).status_code == 404
    assert authenticated_client(guest_admin).get(receipt_url(receipt)).status_code == 404


def test_receipt_finalize_rejects_foreign_makerspace_key(monkeypatch):
    # Use real finalize key checks while mocking object validation away from S3.
    monkeypatch.setattr(
        "apps.procurement.storage.validate_receipt_object",
        lambda object_key: SimpleNamespace(size=10, content_type="application/pdf"),
    )
    monkeypatch.setattr("apps.procurement.storage.finalize_upload", lambda object_key, max_bytes: 10)
    makerspace = make_space("proc-receipt-prefix")
    other_space = make_space("proc-receipt-prefix-other")
    manager = make_space_manager("proc-receipt-prefix-manager", makerspace)
    item = ToBuyItem.objects.create(makerspace=makerspace, kind=ToBuyItem.Kind.HARDWARE, name="Clamp")

    response = authenticated_client(manager).post(
        receipt_list_url(item),
        {"object_key": f"procurement/{other_space.id}/foreign.pdf"},
        format="json",
    )

    assert response.status_code == 400
    assert "object_key" in response.data


def test_validate_receipt_object_sniffs_pdf_and_rejects_html(monkeypatch):
    from apps.procurement import storage

    class FakeBody:
        def __init__(self, data):
            self.data = data

        def read(self, _size):
            return self.data

    class FakeClient:
        def __init__(self, data):
            self.data = data

        def get_object(self, Bucket, Key):
            return {"Body": FakeBody(self.data)}

    monkeypatch.setattr("apps.procurement.storage.object_size", lambda object_key: 123)
    monkeypatch.setattr("apps.procurement.storage._client", lambda: FakeClient(b"%PDF-1.5 receipt"))
    result = storage.validate_receipt_object("procurement/1/receipt.pdf")
    assert result.content_type == "application/pdf"

    monkeypatch.setattr("apps.procurement.storage._client", lambda: FakeClient(b"<html>not a receipt</html>"))
    with pytest.raises(ValidationError):
        storage.validate_receipt_object("procurement/1/receipt.pdf")
