from unittest.mock import Mock

import pytest

from apps.audit.models import AuditLog
from apps.boxes.models import BoxScan
from apps.evidence.storage import EvidenceValidationResult
from apps.hardware_requests.models import (
    HardwareRequest,
    RequesterAccountability,
    ReturnEvent,
)
from tests.return_helpers import (
    active_loans_url,
    authenticated_client,
    make_issued_request,
    make_member,
    make_product,
    make_return_evidence,
    make_space,
    return_payload,
    return_url,
)

pytestmark = pytest.mark.django_db


def test_happy_full_good_return_moves_stock_audits_and_notifies(
    monkeypatch,
    settings,
    django_capture_on_commit_callbacks,
):
    settings.STORAGE_PRESIGN_METHOD = "post"
    makerspace = make_space("return-happy")
    admin = make_member("return-happy-admin", makerspace)
    product = make_product(makerspace)
    hardware_request = make_issued_request(makerspace, admin, [(product, 2)])
    evidence = make_return_evidence(makerspace, admin)
    finalize = Mock(return_value=EvidenceValidationResult(size=123, content_type="image/png"))
    monkeypatch.setattr("apps.evidence.storage.finalize_upload", finalize)
    notify = Mock()
    monkeypatch.setattr(
        "apps.hardware_requests.notifications.notify_request_returned",
        notify,
    )

    with django_capture_on_commit_callbacks(execute=True) as callbacks:
        response = authenticated_client(admin).post(
            return_url(hardware_request),
            return_payload(hardware_request, evidence, remark="Clean and complete."),
            format="json",
        )

    assert response.status_code == 200
    finalize.assert_called_once_with(evidence, settings.EVIDENCE_MAX_BYTES)
    hardware_request.refresh_from_db()
    assert hardware_request.status == HardwareRequest.Status.RETURNED
    assert hardware_request.closed_by == admin
    assert hardware_request.closed_at is not None
    product.refresh_from_db()
    assert product.available_quantity == 10
    assert product.issued_quantity == 0
    assert hardware_request.items.get().returned_quantity == 2
    assert ReturnEvent.objects.filter(request=hardware_request, evidence=evidence).count() == 1
    assert RequesterAccountability.objects.count() == 0
    assert BoxScan.objects.filter(
        request=hardware_request,
        box=hardware_request.assigned_box,
        context=BoxScan.Context.RETURN,
    ).count() == 1
    assert {"request.returned", "evidence.attached", "box.scanned"} <= set(
        AuditLog.objects.values_list("action", flat=True)
    )
    notify.assert_called_once()


def test_damaged_and_missing_return_closes_with_issue_and_creates_accountability(
    monkeypatch,
):
    makerspace = make_space("return-damaged-missing")
    admin = make_member("return-damaged-missing-admin", makerspace)
    product = make_product(makerspace)
    hardware_request = make_issued_request(makerspace, admin, [(product, 3)])
    item = hardware_request.items.get()
    evidence = make_return_evidence(makerspace, admin)
    monkeypatch.setattr("apps.evidence.storage.object_exists", Mock(return_value=True))
    payload = return_payload(hardware_request, evidence)
    payload["resolutions"] = [
        {"item_id": item.id, "returned": 1, "damaged": 1, "missing": 1}
    ]

    response = authenticated_client(admin).post(
        return_url(hardware_request),
        payload,
        format="json",
    )

    assert response.status_code == 200
    hardware_request.refresh_from_db()
    assert hardware_request.status == HardwareRequest.Status.CLOSED_WITH_ISSUE
    product.refresh_from_db()
    assert product.available_quantity == 8
    assert product.issued_quantity == 0
    assert product.damaged_quantity == 1
    assert product.lost_quantity == 1
    item.refresh_from_db()
    assert (item.returned_quantity, item.damaged_quantity, item.missing_quantity) == (
        1,
        1,
        1,
    )
    assert RequesterAccountability.objects.filter(
        request=hardware_request,
        request_item=item,
        evidence_photo=evidence,
    ).count() == 2
    assert {"request.closed_with_issue", "item.damaged", "item.missing"} <= set(
        AuditLog.objects.values_list("action", flat=True)
    )


def test_multi_item_damage_and_loss_records_point_to_correct_items(monkeypatch):
    makerspace = make_space("return-multi-item")
    admin = make_member("return-multi-item-admin", makerspace)
    product_one = make_product(makerspace, name="Scope")
    product_two = make_product(makerspace, name="Meter")
    hardware_request = make_issued_request(
        makerspace,
        admin,
        [(product_one, 1), (product_two, 2)],
    )
    first_item, second_item = list(hardware_request.items.order_by("id"))
    evidence = make_return_evidence(makerspace, admin)
    monkeypatch.setattr("apps.evidence.storage.object_exists", Mock(return_value=True))
    payload = return_payload(hardware_request, evidence)
    payload["resolutions"] = [
        {"item_id": first_item.id, "returned": 0, "damaged": 1, "missing": 0},
        {"item_id": second_item.id, "returned": 1, "damaged": 0, "missing": 1},
    ]

    response = authenticated_client(admin).post(
        return_url(hardware_request),
        payload,
        format="json",
    )

    assert response.status_code == 200
    assert set(
        RequesterAccountability.objects.values_list(
            "request_item_id",
            "issue_type",
            "quantity",
        )
    ) == {
        (first_item.id, RequesterAccountability.IssueType.DAMAGED, 1),
        (second_item.id, RequesterAccountability.IssueType.MISSING, 1),
    }


def test_partial_return_then_complete_return(monkeypatch):
    makerspace = make_space("return-partial")
    admin = make_member("return-partial-admin", makerspace)
    product = make_product(makerspace)
    hardware_request = make_issued_request(makerspace, admin, [(product, 3)])
    item = hardware_request.items.get()
    first_evidence = make_return_evidence(makerspace, admin)
    second_evidence = make_return_evidence(makerspace, admin)
    monkeypatch.setattr("apps.evidence.storage.object_exists", Mock(return_value=True))
    client = authenticated_client(admin)

    first_payload = return_payload(hardware_request, first_evidence, remark="Part one.")
    first_payload["resolutions"] = [
        {"item_id": item.id, "returned": 1, "damaged": 0, "missing": 0}
    ]
    first = client.post(return_url(hardware_request), first_payload, format="json")
    assert first.status_code == 200
    hardware_request.refresh_from_db()
    assert hardware_request.status == HardwareRequest.Status.PARTIALLY_RETURNED
    assert client.get(active_loans_url(makerspace)).data["results"][0]["id"] == hardware_request.id

    second_payload = return_payload(hardware_request, second_evidence, remark="Final.")
    second_payload["resolutions"] = [
        {"item_id": item.id, "returned": 2, "damaged": 0, "missing": 0}
    ]
    second = client.post(return_url(hardware_request), second_payload, format="json")

    assert second.status_code == 200
    hardware_request.refresh_from_db()
    product.refresh_from_db()
    assert hardware_request.status == HardwareRequest.Status.RETURNED
    assert product.issued_quantity == 0
    assert product.available_quantity == 10
    assert ReturnEvent.objects.filter(request=hardware_request).count() == 2
