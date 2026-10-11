import pytest
from django.db import DatabaseError, transaction

from apps.audit.models import AuditLog
from apps.hardware_requests import workflow
from apps.hardware_requests.models import HardwareRequest, RequesterAccountability, ReturnEvent
from apps.hardware_requests.workflow_errors import RequestValidationError, ReturnValidationError
from tests.kit_helpers import BOX_KEY, PRODUCT_KEY, issue_kit, kit_setup, return_kit
from tests.return_helpers import make_issue_evidence, make_return_evidence

pytestmark = pytest.mark.django_db


def test_issue_and_return_record_frozen_checklists():
    data = kit_setup()
    issue_kit(data)
    data.item.refresh_from_db()
    assert data.item.issue_checklist[0]["present"] == 12
    data.product.kit_components = []
    data.product.save(update_fields=["kit_components"])
    returned = return_kit(data, [{"key": PRODUCT_KEY, "present": 12}])
    event = ReturnEvent.objects.get(request=returned)
    assert event.kit_checklist[0]["label"] == "Driver bits"
    assert event.kit_checklist[0]["present"] == 12
    assert "Driver bits: 12/12 present" in event.remark
    assert returned.status == HardwareRequest.Status.RETURNED
    assert AuditLog.objects.filter(action="kit.issue_recorded", makerspace=data.space).count() == 1
    assert AuditLog.objects.filter(action="kit.return_recorded", makerspace=data.space).count() == 1
    with pytest.raises(DatabaseError), transaction.atomic():
        ReturnEvent.objects.filter(pk=event.pk).update(kit_checklist=[])


def test_missing_components_create_only_new_missing_accountability():
    data = kit_setup()
    issue_kit(data, product_present=11)
    returned = return_kit(data, [{"key": PRODUCT_KEY, "present": 10}])
    record = RequesterAccountability.objects.get(request=returned)
    assert record.quantity == 1
    assert record.request_item_id == data.item.pk
    assert record.requester_id == data.borrower.pk
    assert record.evidence_photo_id == ReturnEvent.objects.get(request=returned).evidence_id
    assert record.issue_type == "missing"
    assert returned.status == HardwareRequest.Status.CLOSED_WITH_ISSUE
    data.product.refresh_from_db()
    assert data.product.lost_quantity == 0  # components do not invent product-unit loss


def test_container_component_accountability_has_no_invented_product_line():
    data = kit_setup(product_kit=False, box_kit=True)
    issue_kit(data)
    returned = return_kit(data, [{"key": BOX_KEY, "present": 0}])
    record = RequesterAccountability.objects.get(request=returned)
    assert record.request_item_id is None
    assert "Carry strap" in record.description
    assert returned.status == HardwareRequest.Status.CLOSED_WITH_ISSUE


def test_partial_returns_partition_baseline_without_duplicate_accountability():
    data = kit_setup(quantity=2)
    issue_kit(data)
    data.request = return_kit(data, [{"key": PRODUCT_KEY, "present": 11}], quantity=1)
    assert data.request.status == HardwareRequest.Status.PARTIALLY_RETURNED
    data.request = return_kit(data, [{"key": PRODUCT_KEY, "present": 12}], quantity=1)
    assert data.request.status == HardwareRequest.Status.CLOSED_WITH_ISSUE
    assert RequesterAccountability.objects.filter(request=data.request).count() == 1
    assert ReturnEvent.objects.filter(request=data.request).count() == 2


@pytest.mark.parametrize("counts", [[], [{"key": BOX_KEY, "present": 1}],
    [{"key": PRODUCT_KEY, "present": 12}, {"key": PRODUCT_KEY, "present": 12}],
    [{"key": PRODUCT_KEY, "present": 13}], [{"key": PRODUCT_KEY, "present": -1}]])
def test_issue_refuses_missing_unknown_duplicate_or_invalid_counts_atomically(counts):
    data = kit_setup()
    data.request = workflow.assign_box(data.actor, data.request, data.box.code)
    with pytest.raises(RequestValidationError):
        workflow.issue_request(data.actor, data.request, make_issue_evidence(data.space, data.actor).pk,
                               kit_checklist=counts)
    data.product.refresh_from_db()
    data.request.refresh_from_db()
    assert data.request.status == HardwareRequest.Status.ACCEPTED
    assert data.product.issued_quantity == 0
    assert data.product.reserved_quantity == 1


def test_checklist_never_replaces_issue_box_scan_or_photo():
    data = kit_setup()
    photo = make_issue_evidence(data.space, data.actor)
    data.request.assigned_box = data.box
    data.request.save(update_fields=["assigned_box"])
    with pytest.raises(RequestValidationError, match="Box scan"):
        workflow.issue_request(data.actor, data.request, photo.pk,
                               kit_checklist=[{"key": PRODUCT_KEY, "present": 12}])
    with pytest.raises(RequestValidationError, match="evidence"):
        workflow.issue_request(data.actor, data.request, None,
                               kit_checklist=[{"key": PRODUCT_KEY, "present": 12}])


def test_checklist_never_replaces_return_photo_or_remark():
    data = kit_setup()
    issue_kit(data)
    with pytest.raises(ReturnValidationError, match="remark"):
        return_kit(data, [{"key": PRODUCT_KEY, "present": 12}], remark="")
    with pytest.raises(ReturnValidationError, match="evidence"):
        workflow.return_items(data.actor, data.request, None, "Inspected", data.box.code,
            [{"item_id": data.item.pk, "returned": 1, "damaged": 0, "missing": 0}],
            kit_checklist=[{"key": PRODUCT_KEY, "present": 12}])
    with pytest.raises(RequestValidationError):
        return_kit(data, [])
    assert not ReturnEvent.objects.filter(request=data.request).exists()


def test_outstanding_kit_stays_checkable_after_feature_disabled():
    data = kit_setup()
    issue_kit(data)
    data.space.enabled_features = []
    data.space.save(update_fields=["enabled_features"])
    with pytest.raises(RequestValidationError):
        return_kit(data, [])
    returned = return_kit(data, [{"key": PRODUCT_KEY, "present": 12}])
    assert returned.status == HardwareRequest.Status.RETURNED


def test_foreign_return_evidence_is_refused_with_checklist():
    data = kit_setup()
    issue_kit(data)
    other = kit_setup("foreign")
    with pytest.raises(ReturnValidationError, match="evidence"):
        workflow.return_items(data.actor, data.request, make_return_evidence(other.space, other.actor).pk,
            "Inspected", data.box.code, [{"item_id": data.item.pk, "returned": 1, "damaged": 0, "missing": 0}],
            kit_checklist=[{"key": PRODUCT_KEY, "present": 12}])
    assert not RequesterAccountability.objects.filter(request=data.request).exists()
