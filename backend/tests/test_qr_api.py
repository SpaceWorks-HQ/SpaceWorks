import pytest
from django.db import connection
from django.test import override_settings
from rest_framework.test import APIClient

from apps.boxes.models import QrCode, QrScanEvent
from apps.evidence.models import EvidencePhoto
from apps.accounts.models import User
from apps.inventory.models import InventoryProduct
from apps.makerspaces.models import MakerspaceMembership
from apps.presence import services as presence
from tests.return_helpers import (
    authenticated_client,
    make_accepted_request,
    make_member,
    make_product,
    make_space,
    make_user,
)
from tests.handout_roles import make_handout_member

pytestmark = pytest.mark.django_db


def test_qr_scan_rejects_cross_makerspace_request():
    space_a = make_space("qr-scan-a")
    space_b = make_space("qr-scan-b")
    admin = make_member("qr-scan-admin", space_a)
    product_a = make_product(space_a)
    qr = QrCode.objects.create(
        makerspace=space_a,
        target_type=QrCode.TargetType.PRODUCT,
        target_id=product_a.id,
    )
    foreign_request = make_accepted_request(space_b, make_product(space_b), 1)

    response = authenticated_client(admin).post(
        "/api/v1/admin/qr/scan",
        {
            "payload": qr.payload,
            "context": QrScanEvent.Context.ISSUE,
            "request_id": foreign_request.id,
        },
        format="json",
    )

    assert response.status_code == 400
    assert QrScanEvent.objects.count() == 0


@override_settings(API_CLIENT_AUTH_REQUIRED=False)
def test_cannot_revoke_qr_with_outstanding_loan():
    makerspace = make_space("qr-revoke-loan")
    admin = make_member("qr-revoke-admin", makerspace)
    product = make_product(makerspace, public_self_checkout_enabled=True)
    qr = QrCode.objects.create(
        makerspace=makerspace,
        target_type=QrCode.TargetType.PRODUCT,
        target_id=product.id,
    )

    borrower = make_member("qr-revoke-borrower", makerspace)
    presence.start_session(borrower, makerspace, 60)
    checkout = authenticated_client(borrower).post(
        f"/api/v1/public/{makerspace.slug}/tools/checkout",
        {
            "payload": qr.payload,
            "evidence_id": _public_issue_evidence(makerspace, borrower, "member-1").id,
        },
        format="json",
    )
    assert checkout.status_code == 201

    response = authenticated_client(admin).post(f"/api/v1/admin/qr/{qr.id}/revoke")

    assert response.status_code == 400
    qr.refresh_from_db()
    assert qr.status == QrCode.Status.ACTIVE


def test_admin_can_create_scan_and_revoke_box_qr():
    makerspace = make_space("qr-api")
    admin = make_member("qr-admin", makerspace)
    client = authenticated_client(admin)

    created = client.post(
        "/api/v1/admin/qr/boxes",
        {"makerspace_id": makerspace.id, "label": "Return Bin"},
        format="json",
    )
    qr = QrCode.objects.get(target_type=QrCode.TargetType.BOX)
    scanned = client.post(
        "/api/v1/admin/qr/scan",
        {"payload": qr.payload, "context": QrScanEvent.Context.INVENTORY_CHECK},
        format="json",
    )
    revoked = client.post(f"/api/v1/admin/qr/{qr.id}/revoke")

    assert created.status_code == 201
    assert scanned.status_code == 201
    assert scanned.data["target"]["type"] == "box"
    assert revoked.status_code == 200
    qr.refresh_from_db()
    assert qr.status == QrCode.Status.REVOKED


def test_guest_admin_cannot_manage_qr():
    makerspace = make_space("qr-deny")
    guest = make_handout_member("qr-guest", makerspace)

    response = authenticated_client(guest).post(
        "/api/v1/admin/qr/boxes",
        {"makerspace_id": makerspace.id, "label": "Denied"},
        format="json",
    )

    assert response.status_code == 404


@pytest.mark.parametrize(
    ("membership_role", "global_role"),
    [
        (MakerspaceMembership.Role.INVENTORY_MANAGER, User.Role.REQUESTER),
        (MakerspaceMembership.Role.SPACE_MANAGER, User.Role.SPACE_MANAGER),
    ],
)
def test_suspended_qr_manager_cannot_manage_qr(membership_role, global_role):
    makerspace = make_space(f"qr-suspended-{membership_role}")
    user = make_member(
        f"qr-suspended-{membership_role}",
        makerspace,
        membership_role=membership_role,
        role=global_role,
    )
    user.access_status = User.AccessStatus.SUSPENDED
    user.save(update_fields=["access_status"])

    response = authenticated_client(user).post(
        "/api/v1/admin/qr/boxes",
        {"makerspace_id": makerspace.id, "label": "Denied"},
        format="json",
    )

    assert response.status_code == 403


def test_must_change_password_superadmin_cannot_manage_qr():
    makerspace = make_space("qr-password-rotate")
    superadmin = make_user(
        "qr-password-rotate-super",
        role=User.Role.SUPERADMIN,
        access_status=User.AccessStatus.ACTIVE,
        must_change_password=True,
    )

    response = authenticated_client(superadmin).post(
        "/api/v1/admin/qr/boxes",
        {"makerspace_id": makerspace.id, "label": "Denied"},
        format="json",
    )

    assert response.status_code == 403
    assert QrCode.objects.count() == 0


def test_suspended_staff_cannot_resolve_qr():
    makerspace = make_space("qr-resolve-suspended")
    staff = make_member("qr-resolve-suspended-manager", makerspace)
    staff.access_status = User.AccessStatus.SUSPENDED
    staff.save(update_fields=["access_status"])
    product = make_product(makerspace)
    qr = QrCode.objects.create(
        makerspace=makerspace,
        target_type=QrCode.TargetType.PRODUCT,
        target_id=product.id,
    )

    response = authenticated_client(staff).post(
        "/api/v1/admin/qr/resolve",
        {"payload": qr.payload},
        format="json",
    )

    assert response.status_code == 403
    assert QrScanEvent.objects.count() == 0


def test_qr_scan_event_is_immutable_at_model_and_db():
    makerspace = make_space("qr-immutable")
    admin = make_member("qr-immutable-admin", makerspace)
    product = make_product(makerspace)
    qr = QrCode.objects.create(
        makerspace=makerspace,
        target_type=QrCode.TargetType.PRODUCT,
        target_id=product.id,
        created_by=admin,
    )
    scan = QrScanEvent.objects.create(
        makerspace=makerspace,
        qr_code=qr,
        actor=admin,
        context=QrScanEvent.Context.INVENTORY_CHECK,
    )

    with pytest.raises(RuntimeError):
        scan.save()
    if connection.vendor == "postgresql":
        with pytest.raises(Exception):
            QrScanEvent.objects.filter(pk=scan.pk).update(context=QrScanEvent.Context.REASSIGNMENT)

def test_qr_actions_hide_foreign_and_non_manageable_qr_ids():
    own_space = make_space("qr-hide-own")
    foreign_space = make_space("qr-hide-foreign")
    own_admin = make_member("qr-hide-own-admin", own_space)
    guest = make_handout_member("qr-hide-guest", own_space)
    own_qr = QrCode.objects.create(
        makerspace=own_space,
        target_type=QrCode.TargetType.PRODUCT,
        target_id=make_product(own_space).id,
    )
    foreign_qr = QrCode.objects.create(
        makerspace=foreign_space,
        target_type=QrCode.TargetType.PRODUCT,
        target_id=make_product(foreign_space).id,
    )

    client = authenticated_client(own_admin)
    assert client.get(f"/api/v1/admin/qr/{foreign_qr.id}/print").status_code == 404
    assert client.post(f"/api/v1/admin/qr/{foreign_qr.id}/revoke").status_code == 404
    assert client.post(f"/api/v1/admin/qr/{foreign_qr.id + 999}/revoke").status_code == 404

    guest_client = authenticated_client(guest)
    assert guest_client.get(f"/api/v1/admin/qr/{own_qr.id}/print").status_code == 404
    assert guest_client.post(f"/api/v1/admin/qr/{own_qr.id}/revoke").status_code == 404
    own_qr.refresh_from_db()
    assert own_qr.status == QrCode.Status.ACTIVE


def test_qr_resolve_and_scan_hide_foreign_payloads():
    own_space = make_space("qr-payload-own")
    foreign_space = make_space("qr-payload-foreign")
    own_admin = make_member("qr-payload-own-admin", own_space)
    foreign_qr = QrCode.objects.create(
        makerspace=foreign_space,
        target_type=QrCode.TargetType.PRODUCT,
        target_id=make_product(foreign_space).id,
    )
    client = authenticated_client(own_admin)

    resolved = client.post("/api/v1/admin/qr/resolve", {"payload": foreign_qr.payload}, format="json")
    scanned = client.post(
        "/api/v1/admin/qr/scan",
        {"payload": foreign_qr.payload, "context": QrScanEvent.Context.INVENTORY_CHECK},
        format="json",
    )

    assert resolved.status_code == 404
    assert scanned.status_code == 404
    assert QrScanEvent.objects.count() == 0


def test_qr_scan_endpoint_rejects_internal_only_context():
    makerspace = make_space("qr-scan-context")
    admin = make_member("qr-scan-context-admin", makerspace)
    qr = QrCode.objects.create(
        makerspace=makerspace,
        target_type=QrCode.TargetType.PRODUCT,
        target_id=make_product(makerspace).id,
    )

    response = authenticated_client(admin).post(
        "/api/v1/admin/qr/scan",
        {"payload": qr.payload, "context": QrScanEvent.Context.REASSIGNMENT},
        format="json",
    )

    assert response.status_code == 400
    assert QrScanEvent.objects.count() == 0

def test_qr_rebind_hides_foreign_source_qr_id():
    own_space = make_space("qr-rebind-hide-own")
    foreign_space = make_space("qr-rebind-hide-foreign")
    own_admin = make_member("qr-rebind-hide-admin", own_space)
    target = make_product(own_space)
    foreign_qr = QrCode.objects.create(
        makerspace=foreign_space,
        target_type=QrCode.TargetType.PRODUCT,
        target_id=make_product(foreign_space).id,
    )

    response = authenticated_client(own_admin).post(
        f"/api/v1/admin/qr/{foreign_qr.id}/rebind-target",
        {"target_type": QrCode.TargetType.PRODUCT, "target_id": target.id},
        format="json",
    )

    assert response.status_code == 404


def _public_issue_evidence(makerspace, uploaded_by, identifier):
    return EvidencePhoto.objects.create(
        makerspace=makerspace,
        evidence_type=EvidencePhoto.EvidenceType.ISSUE,
        object_key=f"evidence/{makerspace.id}/issue/{identifier}-{EvidencePhoto.objects.count() + 1}",
        uploaded_by=uploaded_by,
    )


