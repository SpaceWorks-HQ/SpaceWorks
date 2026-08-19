from unittest.mock import Mock

import pytest

from apps.boxes.models import BoxScan
from apps.evidence.storage import StorageUnavailable
from apps.hardware_requests.models import HardwareRequest, ReturnEvent
from tests.return_helpers import (
    authenticated_client,
    make_accepted_request,
    make_box,
    make_issued_request,
    make_issue_evidence,
    make_member,
    make_product,
    make_return_evidence,
    make_space,
    return_payload,
    return_url,
)

pytestmark = pytest.mark.django_db


def test_return_requires_non_blank_remark():
    makerspace = make_space("return-blank-remark")
    admin = make_member("return-blank-remark-admin", makerspace)
    product = make_product(makerspace)
    hardware_request = make_issued_request(makerspace, admin, [(product, 1)])
    evidence = make_return_evidence(makerspace, admin)

    response = authenticated_client(admin).post(
        return_url(hardware_request),
        return_payload(hardware_request, evidence, remark=""),
        format="json",
    )

    assert response.status_code == 400
    assert ReturnEvent.objects.count() == 0


def test_return_without_uploaded_photo_returns_409(monkeypatch):
    makerspace = make_space("return-no-upload")
    admin = make_member("return-no-upload-admin", makerspace)
    product = make_product(makerspace)
    hardware_request = make_issued_request(makerspace, admin, [(product, 1)])
    evidence = make_return_evidence(makerspace, admin)
    monkeypatch.setattr("apps.evidence.storage.object_exists", Mock(return_value=False))

    response = authenticated_client(admin).post(
        return_url(hardware_request),
        return_payload(hardware_request, evidence),
        format="json",
    )

    assert response.status_code == 409
    assert response.data["code"] == "evidence_not_uploaded"
    assert ReturnEvent.objects.count() == 0


def test_return_storage_unavailable_returns_503(monkeypatch):
    makerspace = make_space("return-storage-down")
    admin = make_member("return-storage-down-admin", makerspace)
    product = make_product(makerspace)
    hardware_request = make_issued_request(makerspace, admin, [(product, 1)])
    evidence = make_return_evidence(makerspace, admin)
    monkeypatch.setattr(
        "apps.evidence.storage.object_exists",
        Mock(side_effect=StorageUnavailable("storage unavailable")),
    )

    response = authenticated_client(admin).post(
        return_url(hardware_request),
        return_payload(hardware_request, evidence),
        format="json",
    )

    assert response.status_code == 503
    assert response.data["code"] == "evidence_storage_unavailable"


@pytest.mark.parametrize("size", [0, 101])
def test_return_put_mode_rejects_invalid_evidence_size(monkeypatch, settings, size):
    settings.STORAGE_PRESIGN_METHOD = "put"
    settings.EVIDENCE_MAX_BYTES = 100
    makerspace = make_space(f"return-put-size-{size}")
    admin = make_member(f"return-put-size-admin-{size}", makerspace)
    product = make_product(makerspace)
    hardware_request = make_issued_request(makerspace, admin, [(product, 1)])
    evidence = make_return_evidence(makerspace, admin)
    from apps.evidence.storage import EvidenceObjectValidationError, EvidenceValidationResult

    def validate(key):
        if key == evidence.object_key:
            raise EvidenceObjectValidationError("missing", "missing")
        return EvidenceValidationResult(size=size, content_type="image/png")

    monkeypatch.setattr("apps.evidence.storage.validate_evidence_object", validate)

    response = authenticated_client(admin).post(
        return_url(hardware_request),
        return_payload(hardware_request, evidence),
        format="json",
    )

    assert response.status_code == 400
    assert response.data["code"] == "return_validation_error"
    assert response.data["detail"] == "Return evidence is invalid or exceeds the size limit."


def test_return_with_cross_tenant_evidence_returns_400_without_storage_call(monkeypatch):
    makerspace = make_space("return-invalid-evidence")
    other_space = make_space("return-invalid-evidence-other")
    admin = make_member("return-invalid-evidence-admin", makerspace)
    other_admin = make_member("return-invalid-evidence-other-admin", other_space)
    product = make_product(makerspace)
    hardware_request = make_issued_request(makerspace, admin, [(product, 1)])
    evidence = make_return_evidence(other_space, other_admin)
    object_exists = Mock(return_value=True)
    monkeypatch.setattr("apps.evidence.storage.object_exists", object_exists)

    response = authenticated_client(admin).post(
        return_url(hardware_request),
        return_payload(hardware_request, evidence),
        format="json",
    )

    assert response.status_code == 400
    assert response.data["code"] == "return_validation_error"
    object_exists.assert_not_called()


def test_return_with_wrong_evidence_type_returns_400_without_storage_call(monkeypatch):
    makerspace = make_space("return-wrong-type")
    admin = make_member("return-wrong-type-admin", makerspace)
    product = make_product(makerspace)
    hardware_request = make_issued_request(makerspace, admin, [(product, 1)])
    evidence = make_issue_evidence(makerspace, admin)
    object_exists = Mock(return_value=True)
    monkeypatch.setattr("apps.evidence.storage.object_exists", object_exists)

    response = authenticated_client(admin).post(
        return_url(hardware_request),
        return_payload(hardware_request, evidence),
        format="json",
    )

    assert response.status_code == 400
    assert response.data["code"] == "return_validation_error"
    object_exists.assert_not_called()


def test_return_rejects_box_mismatch_and_creates_no_return_scan(monkeypatch):
    makerspace = make_space("return-box-mismatch")
    admin = make_member("return-box-mismatch-admin", makerspace)
    product = make_product(makerspace)
    hardware_request = make_issued_request(makerspace, admin, [(product, 1)])
    wrong_box = make_box(makerspace, label="B2")
    evidence = make_return_evidence(makerspace, admin)
    monkeypatch.setattr("apps.evidence.storage.object_exists", Mock(return_value=True))

    response = authenticated_client(admin).post(
        return_url(hardware_request),
        return_payload(hardware_request, evidence, box_code=wrong_box.code),
        format="json",
    )

    assert response.status_code == 400
    assert response.data["code"] == "return_validation_error"
    assert not BoxScan.objects.filter(
        request=hardware_request,
        context=BoxScan.Context.RETURN,
    ).exists()


def test_over_resolution_returns_400_and_does_not_move_stock(monkeypatch):
    makerspace = make_space("return-over-resolution")
    admin = make_member("return-over-resolution-admin", makerspace)
    product = make_product(makerspace)
    hardware_request = make_issued_request(makerspace, admin, [(product, 1)])
    item = hardware_request.items.get()
    evidence = make_return_evidence(makerspace, admin)
    monkeypatch.setattr("apps.evidence.storage.object_exists", Mock(return_value=True))
    payload = return_payload(hardware_request, evidence)
    payload["resolutions"] = [
        {"item_id": item.id, "returned": 2, "damaged": 0, "missing": 0}
    ]

    response = authenticated_client(admin).post(
        return_url(hardware_request),
        payload,
        format="json",
    )

    assert response.status_code == 400
    product.refresh_from_db()
    assert product.available_quantity == 9
    assert product.issued_quantity == 1
    assert ReturnEvent.objects.count() == 0


def test_return_on_non_issued_request_returns_409(monkeypatch):
    makerspace = make_space("return-non-issued")
    admin = make_member("return-non-issued-admin", makerspace)
    product = make_product(makerspace)
    hardware_request = make_accepted_request(makerspace, product, 1)
    hardware_request.assigned_box = make_box(makerspace)
    hardware_request.save(update_fields=["assigned_box", "updated_at"])
    item = hardware_request.items.get()
    evidence = make_return_evidence(makerspace, admin)
    monkeypatch.setattr("apps.evidence.storage.object_exists", Mock(return_value=True))

    response = authenticated_client(admin).post(
        return_url(hardware_request),
        {
            "evidence_id": evidence.id,
            "box_code": hardware_request.assigned_box.code,
            "remark": "Trying too early.",
            "resolutions": [
                {"item_id": item.id, "returned": 1, "damaged": 0, "missing": 0}
            ],
        },
        format="json",
    )

    assert response.status_code == 409
    assert response.data["code"] == "invalid_transition"
