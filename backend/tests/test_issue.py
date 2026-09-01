import uuid
from datetime import timedelta
from unittest.mock import Mock

import pytest
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.boxes.models import Box, BoxScan
from apps.evidence.models import EvidencePhoto
from apps.evidence.storage import EvidenceValidationResult, StorageUnavailable
from apps.hardware_requests.models import HardwareRequest, HardwareRequestItem
from apps.inventory import availability
from apps.inventory.availability import InsufficientStock
from apps.inventory.models import InventoryProduct
from apps.makerspaces.models import Makerspace, MakerspaceMembership
from tests.handout_roles import make_handout_member

pytestmark = pytest.mark.django_db


def make_user(username, role=User.Role.REQUESTER, **kw):
    return get_user_model().objects.create_user(
        username=username,
        email=f"{username}@e.com",
        role=role,
        **kw,
    )


def make_space(slug):
    return Makerspace.objects.create(name=slug, slug=slug)


def make_member(
    username,
    makerspace,
    membership_role=MakerspaceMembership.Role.SPACE_MANAGER,
    role=User.Role.SPACE_MANAGER,
):
    user = make_user(username, role=role, access_status=User.AccessStatus.ACTIVE)
    MakerspaceMembership.objects.create(
        user=user,
        makerspace=makerspace,
        role=membership_role,
    )
    return user


def make_product(makerspace, name="Oscilloscope", **overrides):
    defaults = {
        "makerspace": makerspace,
        "name": name,
        "description": f"{name} description",
        "total_quantity": 5,
        "available_quantity": 5,
        "reserved_quantity": 0,
        "is_public": True,
        "is_archived": False,
    }
    defaults.update(overrides)
    return InventoryProduct.objects.create(**defaults)


def make_accepted_request(makerspace, product, qty, requester=None):
    requester = requester or make_user(
        f"requester-{makerspace.slug}-{uuid.uuid4().hex[:8]}",
        access_status=User.AccessStatus.ACTIVE,
    )
    request = HardwareRequest.objects.create(
        makerspace=makerspace,
        requester=requester,
        requester_username=requester.username,
        status=HardwareRequest.Status.ACCEPTED,
    )
    HardwareRequestItem.objects.create(
        request=request,
        product=product,
        requested_quantity=qty,
        accepted_quantity=qty,
    )
    product.available_quantity -= qty
    product.reserved_quantity += qty
    product.save(update_fields=["available_quantity", "reserved_quantity", "updated_at"])
    return request


def authenticated_client(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def assign_box_url(hardware_request):
    return f"/api/v1/admin/requests/{hardware_request.id}/assign-box"


def issue_url(hardware_request):
    return f"/api/v1/admin/requests/{hardware_request.id}/issue"


def active_loans_url(makerspace):
    return f"/api/v1/admin/makerspace/{makerspace.id}/active-loans"


def make_box(makerspace, label="B1"):
    return Box.objects.create(makerspace=makerspace, label=label)


def make_issue_evidence(makerspace, admin):
    return EvidencePhoto.objects.create(
        makerspace=makerspace,
        evidence_type=EvidencePhoto.EvidenceType.ISSUE,
        object_key=f"evidence/{makerspace.id}/issue/{uuid.uuid4().hex}",
        uploaded_by=admin,
    )


def scan_box(request, box, actor):
    return BoxScan.objects.create(
        makerspace=request.makerspace,
        box=box,
        request=request,
        actor=actor,
        context=BoxScan.Context.ISSUE,
    )


def assign_scanned_box(request, box, actor):
    request.assigned_box = box
    request.save(update_fields=["assigned_box", "updated_at"])
    scan_box(request, box, actor)


def issue_payload(evidence, remark="Issued from bench."):
    return {"evidence_id": evidence.id, "remark": remark}


def test_assign_box_sets_box_creates_scan_and_audits():
    makerspace = make_space("assign-box")
    admin = make_member("assign-box-admin", makerspace)
    product = make_product(makerspace)
    hardware_request = make_accepted_request(makerspace, product, 1)
    box = make_box(makerspace)

    response = authenticated_client(admin).post(
        assign_box_url(hardware_request),
        {"box_code": box.code},
        format="json",
    )

    assert response.status_code == 200
    hardware_request.refresh_from_db()
    assert hardware_request.assigned_box == box
    assert BoxScan.objects.filter(
        request=hardware_request,
        box=box,
        context=BoxScan.Context.ISSUE,
    ).count() == 1
    assert set(AuditLog.objects.values_list("action", flat=True)) == {
        "box.assigned",
        "box.scanned",
    }


def test_assign_unknown_box_returns_400():
    makerspace = make_space("assign-unknown")
    admin = make_member("assign-unknown-admin", makerspace)
    product = make_product(makerspace)
    hardware_request = make_accepted_request(makerspace, product, 1)

    response = authenticated_client(admin).post(
        assign_box_url(hardware_request),
        {"box_code": "missing-box-code"},
        format="json",
    )

    assert response.status_code == 400
    assert response.data["code"] == "box_validation_error"


def test_assign_box_on_non_accepted_request_returns_409():
    makerspace = make_space("assign-pending")
    admin = make_member("assign-pending-admin", makerspace)
    product = make_product(makerspace)
    requester = make_user("assign-pending-requester", access_status=User.AccessStatus.ACTIVE)
    hardware_request = HardwareRequest.objects.create(
        makerspace=makerspace,
        requester=requester,
        requester_username=requester.username,
        status=HardwareRequest.Status.PENDING_APPROVAL,
    )
    HardwareRequestItem.objects.create(
        request=hardware_request,
        product=product,
        requested_quantity=1,
    )
    box = make_box(makerspace)

    response = authenticated_client(admin).post(
        assign_box_url(hardware_request),
        {"box_code": box.code},
        format="json",
    )

    assert response.status_code == 409
    assert response.data["code"] == "invalid_transition"


def test_assign_box_already_out_on_another_loan_returns_409():
    makerspace = make_space("assign-occupied")
    admin = make_member("assign-occupied-admin", makerspace)
    product = make_product(makerspace, total_quantity=8, available_quantity=8)
    box = make_box(makerspace)
    first_request = make_accepted_request(makerspace, product, 1)
    first_request.assigned_box = box
    first_request.status = HardwareRequest.Status.ISSUED
    first_request.save(update_fields=["assigned_box", "status", "updated_at"])
    scan_box(first_request, box, admin)
    second_request = make_accepted_request(makerspace, product, 1)

    response = authenticated_client(admin).post(
        assign_box_url(second_request),
        {"box_code": box.code},
        format="json",
    )

    assert response.status_code == 409
    assert response.data["code"] == "box_unavailable"


def test_issue_without_box_scan_returns_400(monkeypatch):
    makerspace = make_space("issue-no-scan")
    admin = make_member("issue-no-scan-admin", makerspace)
    product = make_product(makerspace)
    hardware_request = make_accepted_request(makerspace, product, 1)
    hardware_request.assigned_box = make_box(makerspace)
    hardware_request.save(update_fields=["assigned_box", "updated_at"])
    evidence = make_issue_evidence(makerspace, admin)
    monkeypatch.setattr("apps.evidence.storage.object_exists", Mock(return_value=True))

    response = authenticated_client(admin).post(
        issue_url(hardware_request),
        issue_payload(evidence),
        format="json",
    )

    assert response.status_code == 400
    assert response.data["code"] == "validation_error"


def test_issue_without_uploaded_evidence_returns_409(monkeypatch):
    makerspace = make_space("issue-no-upload")
    admin = make_member("issue-no-upload-admin", makerspace)
    product = make_product(makerspace)
    hardware_request = make_accepted_request(makerspace, product, 1)
    box = make_box(makerspace)
    assign_scanned_box(hardware_request, box, admin)
    evidence = make_issue_evidence(makerspace, admin)
    monkeypatch.setattr("apps.evidence.storage.object_exists", Mock(return_value=False))

    response = authenticated_client(admin).post(
        issue_url(hardware_request),
        issue_payload(evidence),
        format="json",
    )

    assert response.status_code == 409
    assert response.data["code"] == "evidence_not_uploaded"


def test_issue_storage_unavailable_returns_503(monkeypatch):
    makerspace = make_space("issue-storage-down")
    admin = make_member("issue-storage-down-admin", makerspace)
    product = make_product(makerspace)
    hardware_request = make_accepted_request(makerspace, product, 1)
    box = make_box(makerspace)
    assign_scanned_box(hardware_request, box, admin)
    evidence = make_issue_evidence(makerspace, admin)
    monkeypatch.setattr(
        "apps.evidence.storage.object_exists",
        Mock(side_effect=StorageUnavailable("storage unavailable")),
    )

    response = authenticated_client(admin).post(
        issue_url(hardware_request),
        issue_payload(evidence),
        format="json",
    )

    assert response.status_code == 503
    assert response.data["code"] == "evidence_storage_unavailable"


@pytest.mark.parametrize("size", [0, 101])
def test_issue_put_mode_rejects_invalid_evidence_size(monkeypatch, settings, size):
    settings.STORAGE_PRESIGN_METHOD = "put"
    settings.EVIDENCE_MAX_BYTES = 100
    makerspace = make_space(f"issue-put-size-{size}")
    admin = make_member(f"issue-put-size-admin-{size}", makerspace)
    product = make_product(makerspace)
    hardware_request = make_accepted_request(makerspace, product, 1)
    box = make_box(makerspace)
    assign_scanned_box(hardware_request, box, admin)
    evidence = make_issue_evidence(makerspace, admin)
    def validate(key):
        if key == evidence.object_key:
            from apps.evidence.storage import EvidenceObjectValidationError

            raise EvidenceObjectValidationError("missing", "missing")
        return EvidenceValidationResult(size=size, content_type="image/png")

    monkeypatch.setattr("apps.evidence.storage.validate_evidence_object", validate)

    response = authenticated_client(admin).post(
        issue_url(hardware_request),
        issue_payload(evidence),
        format="json",
    )

    assert response.status_code == 400
    assert response.data["code"] == "validation_error"
    assert response.data["detail"] == "Issue evidence is invalid or exceeds the size limit."


def test_issue_with_cross_tenant_or_wrong_type_evidence_returns_400_without_storage_call(
    monkeypatch,
):
    makerspace = make_space("issue-invalid-evidence")
    other_space = make_space("issue-invalid-evidence-other")
    admin = make_member("issue-invalid-evidence-admin", makerspace)
    other_admin = make_member("issue-invalid-evidence-other-admin", other_space)
    product = make_product(makerspace)
    hardware_request = make_accepted_request(makerspace, product, 1)
    box = make_box(makerspace)
    assign_scanned_box(hardware_request, box, admin)
    evidence = EvidencePhoto.objects.create(
        makerspace=other_space,
        evidence_type=EvidencePhoto.EvidenceType.ISSUE,
        object_key=f"evidence/{other_space.id}/issue/{uuid.uuid4().hex}",
        uploaded_by=other_admin,
    )
    object_exists = Mock(return_value=True)
    monkeypatch.setattr("apps.evidence.storage.object_exists", object_exists)

    response = authenticated_client(admin).post(
        issue_url(hardware_request),
        issue_payload(evidence),
        format="json",
    )

    assert response.status_code == 400
    assert response.data["code"] == "validation_error"
    object_exists.assert_not_called()


def test_issue_happy_path(monkeypatch, settings, django_capture_on_commit_callbacks):
    settings.STORAGE_PRESIGN_METHOD = "post"
    makerspace = make_space("issue-happy")
    makerspace.default_loan_days = 7
    makerspace.save(update_fields=["default_loan_days"])
    admin = make_member("issue-happy-admin", makerspace)
    product = make_product(makerspace, total_quantity=5, available_quantity=5)
    hardware_request = make_accepted_request(makerspace, product, 2)
    box = make_box(makerspace)
    assign_scanned_box(hardware_request, box, admin)
    evidence = make_issue_evidence(makerspace, admin)
    finalize = Mock(return_value=EvidenceValidationResult(size=123, content_type="image/png"))
    monkeypatch.setattr("apps.evidence.storage.finalize_upload", finalize)
    notify = Mock()
    monkeypatch.setattr(
        "apps.hardware_requests.notifications.notify_request_issued",
        notify,
    )

    with django_capture_on_commit_callbacks(execute=True) as callbacks:
        response = authenticated_client(admin).post(
            issue_url(hardware_request),
            issue_payload(evidence, remark="Handed over at desk."),
            format="json",
        )

    assert response.status_code == 200
    finalize.assert_called_once_with(evidence, settings.EVIDENCE_MAX_BYTES)
    hardware_request.refresh_from_db()
    assert hardware_request.status == HardwareRequest.Status.ISSUED
    assert hardware_request.issued_by == admin
    assert hardware_request.issued_at is not None
    assert hardware_request.return_due_at is not None
    delta = hardware_request.return_due_at - hardware_request.issued_at
    assert 6 <= delta.days <= 7
    assert hardware_request.issue_evidence == evidence
    product.refresh_from_db()
    assert product.reserved_quantity == 0
    assert product.issued_quantity == 2
    item = hardware_request.items.get()
    assert item.issued_quantity == item.accepted_quantity
    assert {"request.issued", "evidence.attached"} <= set(
        AuditLog.objects.values_list("action", flat=True)
    )
    notify.assert_called_once()

    loans = authenticated_client(admin).get(active_loans_url(makerspace))
    assert loans.status_code == 200
    assert [item["id"] for item in loans.data["results"]] == [hardware_request.id]


def test_issue_preserves_manager_set_due_time(monkeypatch):
    makerspace = make_space("issue-custom-due")
    admin = make_member("issue-custom-due-admin", makerspace)
    product = make_product(makerspace)
    hardware_request = make_accepted_request(makerspace, product, 1)
    custom_due = timezone.now() + timedelta(days=3)
    hardware_request.return_due_at = custom_due
    hardware_request.save(update_fields=["return_due_at", "updated_at"])
    box = make_box(makerspace)
    assign_scanned_box(hardware_request, box, admin)
    evidence = make_issue_evidence(makerspace, admin)
    monkeypatch.setattr("apps.evidence.storage.object_exists", Mock(return_value=True))

    response = authenticated_client(admin).post(
        issue_url(hardware_request),
        issue_payload(evidence),
        format="json",
    )

    assert response.status_code == 200
    hardware_request.refresh_from_db()
    assert hardware_request.return_due_at == custom_due


def test_guest_admin_can_issue_accepted(monkeypatch):
    makerspace = make_space("guest-issue")
    guest_admin = make_handout_member("guest-issue-admin", makerspace)
    product = make_product(makerspace)
    hardware_request = make_accepted_request(makerspace, product, 1)
    box = make_box(makerspace)
    assign_scanned_box(hardware_request, box, guest_admin)
    evidence = make_issue_evidence(makerspace, guest_admin)
    monkeypatch.setattr("apps.evidence.storage.object_exists", Mock(return_value=True))

    response = authenticated_client(guest_admin).post(
        issue_url(hardware_request),
        issue_payload(evidence),
        format="json",
    )

    assert response.status_code == 200
    hardware_request.refresh_from_db()
    assert hardware_request.status == HardwareRequest.Status.ISSUED


def test_suspended_guest_cannot_issue_returns_403(monkeypatch):
    makerspace = make_space("suspended-guest-issue")
    guest_admin = make_handout_member("suspended-guest-issue-admin", makerspace)
    guest_admin.access_status = User.AccessStatus.SUSPENDED
    guest_admin.save(update_fields=["access_status"])
    product = make_product(makerspace)
    hardware_request = make_accepted_request(makerspace, product, 1)
    evidence = make_issue_evidence(makerspace, guest_admin)
    object_exists = Mock(return_value=True)
    monkeypatch.setattr("apps.evidence.storage.object_exists", object_exists)

    response = authenticated_client(guest_admin).post(
        issue_url(hardware_request),
        issue_payload(evidence),
        format="json",
    )

    assert response.status_code == 403
    object_exists.assert_not_called()


def test_cross_tenant_issue_returns_404(monkeypatch):
    makerspace = make_space("cross-tenant-issue")
    other_space = make_space("cross-tenant-issue-other")
    other_admin = make_member("cross-tenant-issue-admin", other_space)
    product = make_product(makerspace)
    owner_admin = make_member("cross-tenant-issue-owner", makerspace)
    hardware_request = make_accepted_request(makerspace, product, 1)
    evidence = make_issue_evidence(makerspace, owner_admin)
    object_exists = Mock(return_value=True)
    monkeypatch.setattr("apps.evidence.storage.object_exists", object_exists)

    response = authenticated_client(other_admin).post(
        issue_url(hardware_request),
        issue_payload(evidence),
        format="json",
    )

    assert response.status_code == 404
    object_exists.assert_not_called()


def test_double_issue_same_request_returns_409(monkeypatch):
    makerspace = make_space("double-issue")
    admin = make_member("double-issue-admin", makerspace)
    product = make_product(makerspace)
    hardware_request = make_accepted_request(makerspace, product, 1)
    box = make_box(makerspace)
    assign_scanned_box(hardware_request, box, admin)
    evidence = make_issue_evidence(makerspace, admin)
    monkeypatch.setattr("apps.evidence.storage.object_exists", Mock(return_value=True))
    client = authenticated_client(admin)

    first = client.post(issue_url(hardware_request), issue_payload(evidence), format="json")
    second = client.post(issue_url(hardware_request), issue_payload(evidence), format="json")

    assert first.status_code == 200
    assert second.status_code == 409
    assert second.data["code"] == "invalid_transition"


def test_reuse_evidence_on_second_request_returns_400(monkeypatch):
    makerspace = make_space("reuse-evidence")
    admin = make_member("reuse-evidence-admin", makerspace)
    product = make_product(makerspace, total_quantity=8, available_quantity=8)
    first_request = make_accepted_request(makerspace, product, 1)
    first_box = make_box(makerspace, label="B1")
    assign_scanned_box(first_request, first_box, admin)
    second_request = make_accepted_request(makerspace, product, 1)
    second_box = make_box(makerspace, label="B2")
    assign_scanned_box(second_request, second_box, admin)
    evidence = make_issue_evidence(makerspace, admin)
    monkeypatch.setattr("apps.evidence.storage.object_exists", Mock(return_value=True))
    client = authenticated_client(admin)

    first = client.post(issue_url(first_request), issue_payload(evidence), format="json")
    second = client.post(issue_url(second_request), issue_payload(evidence), format="json")

    assert first.status_code == 200
    assert second.status_code == 400
    assert second.data["code"] == "validation_error"
    assert second.data["detail"] == "Evidence already used."


def test_two_requests_same_box_second_issue_conflicts_409(monkeypatch):
    makerspace = make_space("same-box-conflict")
    admin = make_member("same-box-conflict-admin", makerspace)
    product = make_product(makerspace, total_quantity=8, available_quantity=8)
    box = make_box(makerspace)
    first_request = make_accepted_request(makerspace, product, 1)
    assign_scanned_box(first_request, box, admin)
    second_request = make_accepted_request(makerspace, product, 1)
    assign_scanned_box(second_request, box, admin)
    first_evidence = make_issue_evidence(makerspace, admin)
    second_evidence = make_issue_evidence(makerspace, admin)
    monkeypatch.setattr("apps.evidence.storage.object_exists", Mock(return_value=True))
    client = authenticated_client(admin)

    first = client.post(
        issue_url(first_request),
        issue_payload(first_evidence),
        format="json",
    )
    second = client.post(
        issue_url(second_request),
        issue_payload(second_evidence),
        format="json",
    )

    assert first.status_code == 200
    assert second.status_code == 409
    assert second.data["code"] == "box_unavailable"


def test_boxscan_is_immutable():
    makerspace = make_space("boxscan-immutable")
    admin = make_member("boxscan-immutable-admin", makerspace)
    product = make_product(makerspace)
    hardware_request = make_accepted_request(makerspace, product, 1)
    box = make_box(makerspace)
    scan = scan_box(hardware_request, box, admin)

    with pytest.raises(RuntimeError):
        scan.save()
    with pytest.raises(RuntimeError):
        scan.delete()


def test_issue_items_raises_insufficient_stock_when_reserved_too_low():
    makerspace = make_space("issue-insufficient-reserved")
    product = make_product(
        makerspace,
        total_quantity=5,
        available_quantity=4,
        reserved_quantity=1,
    )
    requester = make_user(
        "issue-insufficient-reserved-requester",
        access_status=User.AccessStatus.ACTIVE,
    )
    hardware_request = HardwareRequest.objects.create(
        makerspace=makerspace,
        requester=requester,
        requester_username=requester.username,
        status=HardwareRequest.Status.ACCEPTED,
    )
    HardwareRequestItem.objects.create(
        request=hardware_request,
        product=product,
        requested_quantity=2,
        accepted_quantity=2,
    )

    with pytest.raises(InsufficientStock):
        with transaction.atomic():
            availability.issue_items(hardware_request)
