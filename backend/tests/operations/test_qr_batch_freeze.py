import pytest
from rest_framework.exceptions import ValidationError

from apps.operations.services_qr_assets import add_qr_to_batch, mark_batch_printed
from tests.devices.helpers_labels import label_case

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("status", ["printed", "archived"])
@pytest.mark.parametrize("existing", [True, False])
def test_non_draft_batch_cannot_add_or_relabel_even_with_a_stale_instance(status, existing):
    case = label_case(f"qr-freeze-{status}")
    batch = case["batch"]
    item = batch.items.first()
    qr = item.qr_code
    if not existing:
        from apps.boxes.models import QrCode
        from tests.return_helpers import make_product

        product = make_product(case["space"], name="New batch item")
        qr = QrCode.objects.create(makerspace=case["space"], target_type="product",
                                   target_id=product.pk, created_by=case["actor"])
    from apps.operations.models import QrPrintBatch
    QrPrintBatch.objects.filter(pk=batch.pk).update(status=status)
    with pytest.raises(ValidationError):
        add_qr_to_batch(batch, qr, label_text="Changed")
    item.refresh_from_db()
    assert item.label_text != "Changed"
    assert batch.items.count() == 2


def test_manual_mark_printed_uses_the_same_freeze_boundary_as_device_send():
    case = label_case("qr-freeze-manual")
    mark_batch_printed(case["actor"], case["batch"])
    item = case["batch"].items.first()
    response = case["client"].post(f"/api/v1/admin/qr-print-batches/{case['batch'].pk}/items",
        {"qr_code_id": item.qr_code_id, "label_text": "Replacement"}, format="json")
    assert response.status_code == 400
    item.refresh_from_db()
    assert item.label_text != "Replacement"


@pytest.mark.parametrize("status", ["printed", "archived"])
def test_control_admin_cannot_edit_or_reopen_sent_batch(status):
    from django.contrib import admin
    from django.contrib.auth import get_user_model
    from django.test import RequestFactory
    from apps.operations.admin_qr_batches import QrPrintBatchItemInline
    from apps.operations.models import QrPrintBatch

    case = label_case(f"qr-admin-freeze-{status}")
    batch = case["batch"]
    batch.status = status
    request = RequestFactory().get("/control/")
    request.user = get_user_model().objects.create_superuser(
        f"qr-admin-{status}", f"{status}@example.test", "secret")
    batch_admin = admin.site._registry[QrPrintBatch]
    assert not batch_admin.has_change_permission(request, batch)
    assert {"status", "printed_at"} <= set(batch_admin.get_readonly_fields(request, batch))
    inline = QrPrintBatchItemInline(QrPrintBatch, admin.site)
    assert not inline.has_add_permission(request, batch)
    assert not inline.has_change_permission(request, batch)
    assert not inline.has_delete_permission(request, batch)


def test_item_endpoint_emits_audit_only_when_draft_mutation_commits():
    from apps.audit.models import AuditLog

    case = label_case("qr-item-audit")
    item = case["batch"].items.first()
    path = f"/api/v1/admin/qr-print-batches/{case['batch'].pk}/items"
    body = {"qr_code_id": item.qr_code_id, "label_text": "Draft caption"}
    assert case["client"].post(path, body, format="json").status_code == 201
    entry = AuditLog.objects.get(action="qr_print_batch.item_saved")
    assert entry.actor_id == case["actor"].pk and entry.target_id == str(case["batch"].pk)
    mark_batch_printed(case["actor"], case["batch"])
    assert case["client"].post(path, body, format="json").status_code == 400
    assert AuditLog.objects.filter(action="qr_print_batch.item_saved").count() == 1
