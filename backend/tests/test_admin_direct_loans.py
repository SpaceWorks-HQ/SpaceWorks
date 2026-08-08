from datetime import timedelta

import pytest
from django.test import override_settings
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.boxes.models import Box, QrCode, QrScanEvent
from apps.evidence.models import EvidencePhoto
from apps.hardware_requests.models import HardwareRequest, PublicToolLoan
from apps.inventory.models import InventoryAsset, InventoryProduct, TrackingMode
from apps.makerspaces.models import Makerspace, MakerspaceMembership, MakerspaceRole
from apps.presence import services as presence
from tests.return_helpers import make_issue_evidence, make_return_evidence
from tests.handout_roles import make_handout_member

pytestmark = pytest.mark.django_db

_current_direct_makerspace = None


def full_resolutions(loan):
    resolutions = []
    for item in loan.request.items.all():
        remaining = item.issued_quantity - (
            item.returned_quantity + item.damaged_quantity + item.missing_quantity
        )
        if remaining > 0:
            resolutions.append({"item_id": item.id, "returned": remaining})
    return resolutions


def return_body(
    evidence, notes="Returned in good condition.", qr_payload=None, loan=None, resolutions=None
):
    body = {"evidence_id": evidence.id, "notes": notes}
    if qr_payload is not None:
        body["qr_payload"] = qr_payload
    if resolutions is None:
        # Success-path callers pass loan=... so resolutions cover its outstanding
        # units; negative tests error before build_resolutions runs, so the
        # placeholder below just satisfies the serializer's allow_empty=False.
        resolutions = full_resolutions(loan) if loan is not None else [{"item_id": 1, "returned": 1}]
    body["resolutions"] = resolutions
    return body


def valid_looking_return_body():
    return {"evidence_id": 1, "notes": "x"}


def allow_uploaded(monkeypatch, exists=True):
    # Test settings use STORAGE_PRESIGN_METHOD="post", so the direct-return
    # workflow validates the upload via storage.object_exists.
    monkeypatch.setattr("apps.evidence.storage.object_exists", lambda key: exists)


def make_space(slug="direct-loan-space"):
    return Makerspace.objects.create(name=slug, slug=slug)


def make_admin(makerspace):
    user = User.objects.create_user(
        username=f"admin-{makerspace.slug}",
        role=User.Role.SPACE_MANAGER,
        access_status=User.AccessStatus.ACTIVE,
    )
    MakerspaceMembership.objects.create(
        user=user,
        makerspace=makerspace,
        role=MakerspaceMembership.Role.SPACE_MANAGER,
    )
    return user


def eligible_member(makerspace, username="member-direct", display_name="Direct Borrower"):
    member_username = f"{username}-{makerspace.slug}"
    user = User.objects.filter(username=member_username).first()
    if user is None:
        user = User.objects.create_user(
            username=member_username,
            email=f"{member_username}@example.com",
            phone="+15550101010",
            display_name=display_name,
            access_status=User.AccessStatus.ACTIVE,
        )
    MakerspaceMembership.objects.get_or_create(
        makerspace=makerspace,
        user=user,
        defaults={
            "role": MakerspaceMembership.Role.CUSTOM,
            "assigned_role": MakerspaceRole.objects.get(makerspace=makerspace, slug="member"),
        },
    )
    presence.start_session(user, makerspace, 60)
    return user


def make_product(makerspace, **overrides):
    defaults = {
        "makerspace": makerspace,
        "name": "Bench Multimeter",
        "total_quantity": 3,
        "available_quantity": 3,
        "is_public": True,
        "public_self_checkout_enabled": True,
    }
    defaults.update(overrides)
    return InventoryProduct.objects.create(**defaults)


def authed(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def direct_url(makerspace):
    global _current_direct_makerspace
    _current_direct_makerspace = makerspace
    return f"/api/v1/admin/makerspace/{makerspace.id}/direct-loans"


def direct_payload(*, makerspace=None, **overrides):
    makerspace = makerspace or _current_direct_makerspace
    assert makerspace is not None
    borrower = overrides.pop("borrower", None) or eligible_member(makerspace)
    payload = {
        "borrower_id": borrower.id,
    }
    payload.update(overrides)
    if "evidence_id" not in payload:
        payload["evidence_id"] = _direct_issue_evidence(makerspace).id
    return payload

def _direct_issue_evidence(makerspace):
    actor = User.objects.filter(makerspace_memberships__makerspace=makerspace).first()
    if actor is None:
        actor = User.objects.create_user(
            username=f"evidence-{makerspace.slug}",
            access_status=User.AccessStatus.ACTIVE,
        )
    return EvidencePhoto.objects.create(
        makerspace=makerspace,
        evidence_type=EvidencePhoto.EvidenceType.ISSUE,
        object_key=f"evidence/{makerspace.id}/issue/direct-{EvidencePhoto.objects.count() + 1}",
        uploaded_by=actor,
    )

def issue_direct_product_loan(makerspace, admin, product=None):
    product = product or make_product(makerspace)
    client = authed(admin)
    response = client.post(
        direct_url(makerspace),
        direct_payload(items=[{"product_id": product.id, "quantity": 1}]),
        format="json",
    )
    assert response.status_code == 201
    return client, PublicToolLoan.objects.get(), product


def set_staff_domain(makerspace, domain):
    makerspace.frontend_domain = domain
    makerspace.frontend_domain_status = Makerspace.DomainStatus.VERIFIED
    makerspace.save(update_fields=["frontend_domain", "frontend_domain_status"])
    return f"https://{domain}"


@override_settings(API_CLIENT_AUTH_REQUIRED=False)
def test_admin_direct_manual_handout_and_return_logs_product(monkeypatch):
    makerspace = make_space()
    makerspace.default_loan_days = 10
    makerspace.save(update_fields=["default_loan_days"])
    admin = make_admin(makerspace)
    product = make_product(makerspace)
    container = Box.objects.create(makerspace=makerspace, label="Handout bin")
    client = authed(admin)

    issued = client.post(
        direct_url(makerspace),
        direct_payload(
            container_id=container.id,
            due_at="2035-01-01T00:00:00Z",
            items=[{"product_id": product.id, "quantity": 2}],
        ),
        format="json",
    )

    assert issued.status_code == 201
    assert issued.data["source"] == PublicToolLoan.Source.ADMIN_DIRECT
    assert issued.data["container_id"] == container.id
    assert issued.data["container_label"] == "Handout bin"
    product.refresh_from_db()
    assert product.available_quantity == 1
    assert product.issued_quantity == 2
    request = HardwareRequest.objects.get()
    assert issued.data["issue_evidence_id"] == request.issue_evidence_id
    assert request.status == HardwareRequest.Status.ISSUED
    assert request.issued_by == admin
    assert request.requester_name == "Direct Borrower"
    assert request.requester_contact_email == f"member-direct-{makerspace.slug}@example.com"
    assert request.requester_contact_phone == "+15550101010"
    loan = PublicToolLoan.objects.get()
    assert loan.qr_code_id is None
    assert loan.container == container
    assert loan.due_at is not None
    assert request.return_due_at == loan.due_at
    assert loan.due_at.year != 2035
    assert abs((loan.due_at - loan.checked_out_at) - timedelta(days=10)) < timedelta(
        seconds=2
    )
    assert AuditLog.objects.filter(
        action="admin_direct.checked_out",
        target_type="inventory.inventoryproduct",
        target_id=str(product.id),
    ).exists()

    evidence = make_return_evidence(makerspace, admin)
    allow_uploaded(monkeypatch)
    returned = client.post(
        f"/api/v1/admin/direct-loans/{loan.id}/return",
        return_body(evidence, notes="All good on return.", loan=loan),
        format="json",
    )

    assert returned.status_code == 200
    assert returned.data["status"] == PublicToolLoan.Status.RETURNED
    assert returned.data["return_evidence_id"] == evidence.id
    assert returned.data["return_notes"] == "All good on return."
    loan.refresh_from_db()
    assert loan.return_evidence_id == evidence.id
    assert loan.return_notes == "All good on return."
    product.refresh_from_db()
    assert product.available_quantity == 3
    assert product.issued_quantity == 0
    assert AuditLog.objects.filter(
        action="admin_direct.returned",
        target_type="inventory.inventoryproduct",
        target_id=str(product.id),
    ).exists()
    assert AuditLog.objects.filter(
        action="evidence.attached",
        target_type="evidence.evidencephoto",
        target_id=str(evidence.id),
    ).exists()

    logs = client.get(
        "/api/v1/admin/audit-logs",
        {"target_type": "inventory.inventoryproduct", "target_id": str(product.id)},
    )
    assert logs.status_code == 200
    assert logs.data["count"] >= 2


@override_settings(API_CLIENT_AUTH_REQUIRED=False)
def test_direct_loan_requires_selected_member():
    makerspace = make_space("direct-missing-member")
    admin = make_admin(makerspace)
    product = make_product(makerspace)
    payload = direct_payload(
        makerspace=makerspace,
        borrower=eligible_member(makerspace),
        items=[{"product_id": product.id, "quantity": 1}],
    )
    payload.pop("borrower_id")

    response = authed(admin).post(
        direct_url(makerspace),
        payload,
        format="json",
    )

    assert response.status_code == 400
    assert "borrower_id" in response.data
    assert PublicToolLoan.objects.count() == 0


@override_settings(API_CLIENT_AUTH_REQUIRED=False)
def test_admin_direct_handout_allows_non_self_checkout_product():
    makerspace = make_space("direct-disabled")
    admin = make_admin(makerspace)
    product = make_product(makerspace, public_self_checkout_enabled=False)

    response = authed(admin).post(
        direct_url(makerspace),
        direct_payload(items=[{"product_id": product.id, "quantity": 1}]),
        format="json",
    )

    assert response.status_code == 201
    assert PublicToolLoan.objects.count() == 1


@override_settings(API_CLIENT_AUTH_REQUIRED=False)
def test_admin_direct_qr_handout_allows_non_public_non_self_checkout_product():
    makerspace = make_space("direct-qr-private")
    admin = make_admin(makerspace)
    product = make_product(
        makerspace,
        is_public=False,
        public_self_checkout_enabled=False,
    )
    qr = make_qr(makerspace, product)

    response = authed(admin).post(
        direct_url(makerspace),
        direct_payload(qr_payloads=[qr.payload]),
        format="json",
    )

    assert response.status_code == 201
    assert response.data["items"] == [{"product_name": product.name, "quantity": 1}]
    product.refresh_from_db()
    assert product.available_quantity == 2
    assert product.issued_quantity == 1
    loan = PublicToolLoan.objects.get()
    assert loan.source == PublicToolLoan.Source.ADMIN_DIRECT
    assert loan.qr_ids == [qr.id]


def make_qr(makerspace, product):
    return QrCode.objects.create(
        makerspace=makerspace,
        target_type=QrCode.TargetType.PRODUCT,
        target_id=product.id,
    )


def make_asset_qr(makerspace, asset):
    return QrCode.objects.create(
        makerspace=makerspace,
        target_type=QrCode.TargetType.ASSET,
        target_id=asset.id,
    )


@override_settings(API_CLIENT_AUTH_REQUIRED=False)
def test_suspended_admin_cannot_issue_direct_loan():
    makerspace = make_space("direct-suspended")
    admin = make_admin(makerspace)
    admin.access_status = User.AccessStatus.SUSPENDED
    admin.save(update_fields=["access_status"])
    product = make_product(makerspace)

    response = authed(admin).post(
        direct_url(makerspace),
        direct_payload(items=[{"product_id": product.id, "quantity": 1}]),
        format="json",
    )

    assert response.status_code == 403
    assert PublicToolLoan.objects.count() == 0
    product.refresh_from_db()
    assert product.issued_quantity == 0


@override_settings(API_CLIENT_AUTH_REQUIRED=False)
def test_direct_loan_originless_list_uses_membership_fallback():
    makerspace = make_space("direct-originless-list")
    admin = make_admin(makerspace)
    product = make_product(makerspace)
    client = authed(admin)

    issued = client.post(
        direct_url(makerspace),
        direct_payload(items=[{"product_id": product.id, "quantity": 1}]),
        format="json",
    )
    listed = client.get(direct_url(makerspace))

    assert issued.status_code == 201
    assert listed.status_code == 200


@override_settings(API_CLIENT_AUTH_REQUIRED=False)
def test_direct_loan_rejects_different_staff_origin_for_scoped_views():
    primary = make_space("direct-origin-primary")
    other = make_space("direct-origin-other")
    set_staff_domain(primary, "primary.example.com")
    wrong_origin = set_staff_domain(other, "other.example.com")
    admin = make_admin(primary)
    product = make_product(primary, total_quantity=5, available_quantity=5)
    client = authed(admin)

    issued = client.post(
        direct_url(primary),
        direct_payload(items=[{"product_id": product.id, "quantity": 1}]),
        format="json",
    )
    assert issued.status_code == 201
    loan = PublicToolLoan.objects.get()

    listed = client.get(direct_url(primary), HTTP_ORIGIN=wrong_origin)
    created = client.post(
        direct_url(primary),
        direct_payload(
            items=[{"product_id": product.id, "quantity": 1}],
        ),
        format="json",
        HTTP_ORIGIN=wrong_origin,
    )
    members = client.get(
        f"/api/v1/admin/makerspace/{primary.id}/direct-loan-members",
        HTTP_ORIGIN=wrong_origin,
    )
    returned = client.post(
        f"/api/v1/admin/direct-loans/{loan.id}/return",
        valid_looking_return_body(),
        format="json",
        HTTP_ORIGIN=wrong_origin,
    )

    assert listed.status_code == 403
    assert created.status_code == 403
    assert members.status_code == 403
    assert returned.status_code == 404
    assert PublicToolLoan.objects.count() == 1
    loan.refresh_from_db()
    assert loan.status == PublicToolLoan.Status.CHECKED_OUT


@override_settings(API_CLIENT_AUTH_REQUIRED=False)
def test_direct_return_hides_cross_tenant_and_missing_loan_ids():
    primary = make_space("direct-return-primary")
    other = make_space("direct-return-other")
    primary_admin = make_admin(primary)
    other_admin = make_admin(other)
    other_product = make_product(other)

    issued = authed(other_admin).post(
        direct_url(other),
        direct_payload(items=[{"product_id": other_product.id, "quantity": 1}]),
        format="json",
    )
    assert issued.status_code == 201
    other_loan = PublicToolLoan.objects.get()
    client = authed(primary_admin)

    cross_tenant = client.post(
        f"/api/v1/admin/direct-loans/{other_loan.id}/return",
        valid_looking_return_body(),
        format="json",
    )
    missing = client.post(
        "/api/v1/admin/direct-loans/999999/return",
        valid_looking_return_body(),
        format="json",
    )

    assert cross_tenant.status_code == 404
    assert missing.status_code == 404
    other_loan.refresh_from_db()
    assert other_loan.status == PublicToolLoan.Status.CHECKED_OUT


@override_settings(API_CLIENT_AUTH_REQUIRED=False)
def test_direct_return_requires_evidence_id():
    makerspace = make_space("direct-return-missing-evidence")
    admin = make_admin(makerspace)
    client, loan, product = issue_direct_product_loan(makerspace, admin)

    response = client.post(
        f"/api/v1/admin/direct-loans/{loan.id}/return",
        {"notes": "Returned in good condition."},
        format="json",
    )

    assert response.status_code == 400
    loan.refresh_from_db()
    product.refresh_from_db()
    assert loan.status == PublicToolLoan.Status.CHECKED_OUT
    assert product.issued_quantity == 1


@override_settings(API_CLIENT_AUTH_REQUIRED=False)
def test_direct_return_rejects_blank_notes():
    makerspace = make_space("direct-return-blank-notes")
    admin = make_admin(makerspace)
    client, loan, _product = issue_direct_product_loan(makerspace, admin)
    evidence = make_return_evidence(makerspace, admin)

    response = client.post(
        f"/api/v1/admin/direct-loans/{loan.id}/return",
        return_body(evidence, notes="  "),
        format="json",
    )

    assert response.status_code == 400


@override_settings(API_CLIENT_AUTH_REQUIRED=False)
def test_direct_return_rejects_issue_evidence():
    makerspace = make_space("direct-return-wrong-evidence")
    admin = make_admin(makerspace)
    client, loan, _product = issue_direct_product_loan(makerspace, admin)
    evidence = make_issue_evidence(makerspace, admin)

    response = client.post(
        f"/api/v1/admin/direct-loans/{loan.id}/return",
        return_body(evidence),
        format="json",
    )

    assert response.status_code == 400
    assert response.data["detail"] == "Invalid return evidence."
    assert response.data["code"] == "validation_error"


@override_settings(API_CLIENT_AUTH_REQUIRED=False)
def test_direct_return_rejects_other_makerspace_evidence():
    makerspace = make_space("direct-return-evidence-space")
    other = make_space("direct-return-evidence-other")
    admin = make_admin(makerspace)
    other_admin = make_admin(other)
    client, loan, _product = issue_direct_product_loan(makerspace, admin)
    evidence = make_return_evidence(other, other_admin)

    response = client.post(
        f"/api/v1/admin/direct-loans/{loan.id}/return",
        return_body(evidence),
        format="json",
    )

    assert response.status_code == 400
    assert response.data["detail"] == "Invalid return evidence."
    assert response.data["code"] == "validation_error"


@override_settings(API_CLIENT_AUTH_REQUIRED=False)
def test_direct_return_rejects_not_uploaded_evidence(monkeypatch):
    makerspace = make_space("direct-return-not-uploaded")
    admin = make_admin(makerspace)
    client, loan, _product = issue_direct_product_loan(makerspace, admin)
    evidence = make_return_evidence(makerspace, admin)
    allow_uploaded(monkeypatch, exists=False)

    response = client.post(
        f"/api/v1/admin/direct-loans/{loan.id}/return",
        return_body(evidence),
        format="json",
    )

    assert response.status_code == 409
    assert response.data["code"] == "evidence_not_uploaded"
    assert response.data["detail"] == "Return evidence has not been uploaded."


@override_settings(API_CLIENT_AUTH_REQUIRED=False)
def test_direct_return_rejects_already_returned_loan(monkeypatch):
    makerspace = make_space("direct-return-already-returned")
    admin = make_admin(makerspace)
    client, loan, _product = issue_direct_product_loan(makerspace, admin)
    evidence = make_return_evidence(makerspace, admin)
    allow_uploaded(monkeypatch)

    first = client.post(
        f"/api/v1/admin/direct-loans/{loan.id}/return",
        return_body(evidence, loan=loan),
        format="json",
    )
    second = client.post(
        f"/api/v1/admin/direct-loans/{loan.id}/return",
        return_body(evidence),
        format="json",
    )

    assert first.status_code == 200
    assert second.status_code == 409
    assert second.data["code"] == "invalid_transition"
    assert second.data["detail"] == "Direct loan is not currently checked out."


@override_settings(API_CLIENT_AUTH_REQUIRED=False)
def test_every_qr_in_multi_qr_direct_loan_is_tracked(monkeypatch):
    makerspace = make_space("direct-multi-qr")
    admin = make_admin(makerspace)
    product_a = make_product(makerspace, name="Soldering Iron")
    product_b = make_product(makerspace, name="Hot Air Station")
    qr_a = make_qr(makerspace, product_a)
    qr_b = make_qr(makerspace, product_b)
    client = authed(admin)

    issued = client.post(
        direct_url(makerspace),
        direct_payload(qr_payloads=[qr_a.payload, qr_b.payload]),
        format="json",
    )

    assert issued.status_code == 201
    loan = PublicToolLoan.objects.get()
    # First QR holds the FK; both QRs are recorded so neither can be re-issued.
    assert loan.qr_code_id == qr_a.id
    assert sorted(loan.qr_ids) == sorted([qr_a.id, qr_b.id])

    # The second QR must now read as already checked out (the bug let it through).
    reissue = client.post(
        direct_url(makerspace),
        direct_payload(qr_payloads=[qr_b.payload]),
        format="json",
    )

    assert reissue.status_code == 409
    assert PublicToolLoan.objects.count() == 1

    evidence = make_return_evidence(makerspace, admin)
    allow_uploaded(monkeypatch)
    returned = client.post(
        f"/api/v1/admin/direct-loans/{loan.id}/return",
        return_body(evidence, qr_payload=qr_a.payload, loan=loan),
        format="json",
    )

    assert returned.status_code == 200
    loan.refresh_from_db()
    product_a.refresh_from_db()
    product_b.refresh_from_db()
    assert loan.status == PublicToolLoan.Status.RETURNED
    assert product_a.available_quantity == 3
    assert product_a.issued_quantity == 0
    assert product_b.available_quantity == 3
    assert product_b.issued_quantity == 0


@override_settings(API_CLIENT_AUTH_REQUIRED=False)
def test_direct_return_requires_matching_qr_for_qr_loan(monkeypatch):
    makerspace = make_space("direct-return-qr-required")
    admin = make_admin(makerspace)
    product = make_product(makerspace, name="Loaned QR Tool")
    other_product = make_product(makerspace, name="Other QR Tool")
    qr = make_qr(makerspace, product)
    other_qr = make_qr(makerspace, other_product)
    client = authed(admin)
    issued = client.post(
        direct_url(makerspace),
        direct_payload(qr_payloads=[qr.payload]),
        format="json",
    )
    assert issued.status_code == 201
    loan = PublicToolLoan.objects.get()
    allow_uploaded(monkeypatch)

    missing_scan = client.post(
        f"/api/v1/admin/direct-loans/{loan.id}/return",
        return_body(make_return_evidence(makerspace, admin)),
        format="json",
    )
    assert missing_scan.status_code == 400
    assert missing_scan.data["detail"] == "Return QR scan is required."

    wrong_scan = client.post(
        f"/api/v1/admin/direct-loans/{loan.id}/return",
        return_body(make_return_evidence(makerspace, admin), qr_payload=other_qr.payload),
        format="json",
    )
    assert wrong_scan.status_code == 400
    assert wrong_scan.data["detail"] == "Scanned QR does not match this direct loan."

    returned = client.post(
        f"/api/v1/admin/direct-loans/{loan.id}/return",
        return_body(make_return_evidence(makerspace, admin), qr_payload=qr.payload, loan=loan),
        format="json",
    )

    assert returned.status_code == 200
    loan.refresh_from_db()
    assert loan.status == PublicToolLoan.Status.RETURNED
    assert QrScanEvent.objects.filter(
        qr_code=qr,
        request=loan.request,
        context=QrScanEvent.Context.RETURN,
        actor=admin,
    ).exists()


@override_settings(API_CLIENT_AUTH_REQUIRED=False)
def test_direct_return_requires_container_qr_when_container_has_active_qr(monkeypatch):
    makerspace = make_space("direct-return-container-qr")
    admin = make_admin(makerspace)
    product = make_product(makerspace)
    container = Box.objects.create(makerspace=makerspace, label="Return tote")
    container_qr = QrCode.objects.create(
        makerspace=makerspace,
        target_type=QrCode.TargetType.BOX,
        target_id=container.id,
    )
    client = authed(admin)
    issued = client.post(
        direct_url(makerspace),
        direct_payload(
            container_id=container.id,
            items=[{"product_id": product.id, "quantity": 1}],
        ),
        format="json",
    )
    assert issued.status_code == 201
    loan = PublicToolLoan.objects.get()
    allow_uploaded(monkeypatch)

    missing_scan = client.post(
        f"/api/v1/admin/direct-loans/{loan.id}/return",
        return_body(make_return_evidence(makerspace, admin)),
        format="json",
    )
    assert missing_scan.status_code == 400
    assert missing_scan.data["detail"] == "Return QR scan is required."

    returned = client.post(
        f"/api/v1/admin/direct-loans/{loan.id}/return",
        return_body(make_return_evidence(makerspace, admin), qr_payload=container_qr.payload, loan=loan),
        format="json",
    )

    assert returned.status_code == 200
    assert QrScanEvent.objects.filter(
        qr_code=container_qr,
        request=loan.request,
        context=QrScanEvent.Context.RETURN,
        actor=admin,
    ).exists()


@override_settings(API_CLIENT_AUTH_REQUIRED=False)
def test_direct_loan_rejects_duplicate_qr_payload():
    makerspace = make_space("direct-dup-qr")
    admin = make_admin(makerspace)
    product = make_product(makerspace, total_quantity=5, available_quantity=5)
    qr = make_qr(makerspace, product)

    response = authed(admin).post(
        direct_url(makerspace),
        direct_payload(qr_payloads=[qr.payload, qr.payload]),
        format="json",
    )

    # Same QR twice must not decrement stock twice.
    assert response.status_code == 409
    assert PublicToolLoan.objects.count() == 0
    product.refresh_from_db()
    assert product.available_quantity == 5
    assert product.issued_quantity == 0


@override_settings(API_CLIENT_AUTH_REQUIRED=False)
def test_direct_loan_rejects_product_qr_for_individual_tracked_product():
    makerspace = make_space("direct-individual-product-qr")
    admin = make_admin(makerspace)
    product = make_product(makerspace, tracking_mode=TrackingMode.INDIVIDUAL)
    qr = make_qr(makerspace, product)

    response = authed(admin).post(
        direct_url(makerspace),
        direct_payload(qr_payloads=[qr.payload]),
        format="json",
    )

    assert response.status_code == 400
    assert response.data["detail"] == (
        "Individual-tracked products require a scanned asset QR."
    )
    assert PublicToolLoan.objects.count() == 0
    product.refresh_from_db()
    assert product.available_quantity == 3
    assert product.issued_quantity == 0


@override_settings(API_CLIENT_AUTH_REQUIRED=False)
def test_direct_loan_accepts_asset_qr_for_individual_tracked_product():
    makerspace = make_space("direct-individual-asset-qr")
    admin = make_admin(makerspace)
    product = make_product(
        makerspace,
        tracking_mode=TrackingMode.INDIVIDUAL,
        total_quantity=1,
        available_quantity=1,
    )
    asset = InventoryAsset.objects.create(
        makerspace=makerspace,
        product=product,
        asset_tag="IND-1",
    )
    qr = make_asset_qr(makerspace, asset)

    response = authed(admin).post(
        direct_url(makerspace),
        direct_payload(qr_payloads=[qr.payload]),
        format="json",
    )

    assert response.status_code == 201
    assert response.data["items"] == [{"product_name": product.name, "quantity": 1}]
    asset.refresh_from_db()
    assert asset.status == InventoryAsset.Status.ISSUED
    product.refresh_from_db()
    assert product.available_quantity == 0
    assert product.issued_quantity == 1


@override_settings(API_CLIENT_AUTH_REQUIRED=False)
def test_direct_loan_rejects_box_qr_fallback_for_individual_tracked_product():
    makerspace = make_space("direct-individual-box")
    admin = make_admin(makerspace)
    box = Box.objects.create(makerspace=makerspace, label="Individual shelf")
    product = make_product(
        makerspace,
        box=box,
        tracking_mode=TrackingMode.INDIVIDUAL,
        total_quantity=1,
        available_quantity=1,
    )
    qr = QrCode.objects.create(
        makerspace=makerspace,
        target_type=QrCode.TargetType.BOX,
        target_id=box.id,
    )

    response = authed(admin).post(
        direct_url(makerspace),
        direct_payload(qr_payloads=[qr.payload]),
        format="json",
    )

    assert response.status_code == 400
    assert response.data["detail"] == (
        "Individual-tracked products require a scanned asset QR."
    )
    assert PublicToolLoan.objects.count() == 0
    product.refresh_from_db()
    assert product.available_quantity == 1
    assert product.issued_quantity == 0


@override_settings(API_CLIENT_AUTH_REQUIRED=False)
def test_direct_loan_rejects_inactive_container():
    makerspace = make_space("direct-inactive-container")
    admin = make_admin(makerspace)
    product = make_product(makerspace)
    container = Box.objects.create(
        makerspace=makerspace,
        label="Inactive tote",
        is_active=False,
    )

    response = authed(admin).post(
        direct_url(makerspace),
        direct_payload(
            container_id=container.id,
            items=[{"product_id": product.id, "quantity": 1}],
        ),
        format="json",
    )

    assert response.status_code == 400
    assert response.data["detail"] == "Container is not active."
    assert PublicToolLoan.objects.count() == 0


@override_settings(API_CLIENT_AUTH_REQUIRED=False)
def test_direct_loan_duplicate_active_container_returns_409():
    makerspace = make_space("direct-duplicate-container")
    admin = make_admin(makerspace)
    first = make_product(makerspace, name="First Tool")
    second = make_product(makerspace, name="Second Tool")
    container = Box.objects.create(makerspace=makerspace, label="Loan tote")
    client = authed(admin)

    created = client.post(
        direct_url(makerspace),
        direct_payload(
            borrower=eligible_member(makerspace, "member-direct-1"),
            container_id=container.id,
            items=[{"product_id": first.id, "quantity": 1}],
        ),
        format="json",
    )
    assert created.status_code == 201

    duplicate = client.post(
        direct_url(makerspace),
        direct_payload(
            borrower=eligible_member(makerspace, "member-direct-2"),
            container_id=container.id,
            items=[{"product_id": second.id, "quantity": 1}],
        ),
        format="json",
    )

    assert duplicate.status_code == 409
    assert duplicate.data["detail"] == (
        "That container is already out on another direct handout."
    )
    assert PublicToolLoan.objects.count() == 1
    second.refresh_from_db()
    assert second.available_quantity == 3
    assert second.issued_quantity == 0


def make_guest(makerspace):
    return make_handout_member(f"guest-{makerspace.slug}", makerspace)


@override_settings(API_CLIENT_AUTH_REQUIRED=False)
def test_handout_role_can_create_direct_loan():
    makerspace = make_space("direct-guest-allow")
    guest = make_guest(makerspace)
    product = make_product(makerspace)

    response = authed(guest).post(
        direct_url(makerspace),
        direct_payload(items=[{"product_id": product.id, "quantity": 1}]),
        format="json",
    )

    assert response.status_code == 201
    assert PublicToolLoan.objects.count() == 1


@override_settings(API_CLIENT_AUTH_REQUIRED=False)
def test_direct_return_rejects_self_checkout_loan():
    makerspace = make_space("direct-return-guard")
    admin = make_admin(makerspace)
    member = eligible_member(makerspace, "member-x", "Self Checkout")
    product = make_product(makerspace, public_self_checkout_enabled=True)
    qr = make_qr(makerspace, product)

    checkout = authed(member).post(
        f"/api/v1/public/{makerspace.slug}/tools/checkout",
        {
            "payload": qr.payload,
            "evidence_id": _public_issue_evidence(makerspace, member).id,
        },
        format="json",
    )
    assert checkout.status_code == 201
    loan = PublicToolLoan.objects.get(source=PublicToolLoan.Source.PUBLIC_SELF_CHECKOUT)

    response = authed(admin).post(
        f"/api/v1/admin/direct-loans/{loan.id}/return",
        valid_looking_return_body(),
        format="json",
    )

    # The admin direct-return must not touch a public self-checkout loan.
    assert response.status_code == 404
    loan.refresh_from_db()
    assert loan.status == PublicToolLoan.Status.CHECKED_OUT


@override_settings(API_CLIENT_AUTH_REQUIRED=False)
def test_direct_return_rejects_reused_evidence_across_loans(monkeypatch):
    # One return photo per handover: a return EvidencePhoto can back at most one
    # direct-loan return (mirrors ReturnEvent.evidence single-use for requests).
    makerspace = make_space("direct-return-reuse")
    admin = make_admin(makerspace)
    client = authed(admin)
    product_a = make_product(makerspace, name="Reuse Tool A")
    product_b = make_product(makerspace, name="Reuse Tool B")
    issued_a = client.post(
        direct_url(makerspace),
        direct_payload(items=[{"product_id": product_a.id, "quantity": 1}]),
        format="json",
    )
    issued_b = client.post(
        direct_url(makerspace),
        direct_payload(items=[{"product_id": product_b.id, "quantity": 1}]),
        format="json",
    )
    assert issued_a.status_code == 201
    assert issued_b.status_code == 201
    loan_a_id = issued_a.data["id"]
    loan_b_id = issued_b.data["id"]
    evidence = make_return_evidence(makerspace, admin)
    allow_uploaded(monkeypatch)

    first = client.post(
        f"/api/v1/admin/direct-loans/{loan_a_id}/return",
        return_body(evidence, loan=PublicToolLoan.objects.get(pk=loan_a_id)),
        format="json",
    )
    assert first.status_code == 200

    second = client.post(
        f"/api/v1/admin/direct-loans/{loan_b_id}/return",
        return_body(evidence),
        format="json",
    )
    assert second.status_code == 400
    assert (
        PublicToolLoan.objects.get(pk=loan_b_id).status
        == PublicToolLoan.Status.CHECKED_OUT
    )


@override_settings(API_CLIENT_AUTH_REQUIRED=False)
def test_direct_return_rejects_evidence_used_by_reviewed_return(monkeypatch):
    # Cross-workflow single-use: a RETURN photo already attached to a reviewed
    # request's ReturnEvent cannot be reused for a direct-loan return.
    from apps.hardware_requests.models import ReturnEvent

    makerspace = make_space("direct-return-reviewed-reuse")
    admin = make_admin(makerspace)
    client, loan, _ = issue_direct_product_loan(makerspace, admin)
    evidence = make_return_evidence(makerspace, admin)
    box = Box.objects.create(makerspace=makerspace, label="Reviewed return box")
    reviewed_request = HardwareRequest.objects.create(
        makerspace=makerspace,
        requester=admin,
        requester_username=admin.username,
        status=HardwareRequest.Status.RETURNED,
        assigned_box=box,
        issued_by=admin,
    )
    ReturnEvent.objects.create(
        request=reviewed_request,
        makerspace=makerspace,
        box=box,
        evidence=evidence,
        remark="reviewed return",
        actor=admin,
    )
    allow_uploaded(monkeypatch)

    response = client.post(
        f"/api/v1/admin/direct-loans/{loan.id}/return",
        return_body(evidence),
        format="json",
    )

    assert response.status_code == 400
    loan.refresh_from_db()
    assert loan.status == PublicToolLoan.Status.CHECKED_OUT






def _public_issue_evidence(makerspace, user):
    return EvidencePhoto.objects.create(
        makerspace=makerspace,
        evidence_type=EvidencePhoto.EvidenceType.ISSUE,
        object_key=f"evidence/{makerspace.id}/issue/{user.id}-{EvidencePhoto.objects.count() + 1}",
        uploaded_by=user,
    )


# --- Phase 5: direct-loan return resolutions + accountability ---


@override_settings(API_CLIENT_AUTH_REQUIRED=False)
def test_direct_return_damaged_routes_to_buckets_and_accountability(monkeypatch):
    from apps.hardware_requests.models import RequesterAccountability, ReturnEvent

    makerspace = make_space("direct-return-damaged")
    admin = make_admin(makerspace)
    product = make_product(makerspace, total_quantity=3, available_quantity=3)
    client = authed(admin)
    issued = client.post(
        direct_url(makerspace),
        direct_payload(items=[{"product_id": product.id, "quantity": 2}]),
        format="json",
    )
    assert issued.status_code == 201
    loan = PublicToolLoan.objects.get()
    item = loan.request.items.get()
    evidence = make_return_evidence(makerspace, admin)
    allow_uploaded(monkeypatch)

    returned = client.post(
        f"/api/v1/admin/direct-loans/{loan.id}/return",
        return_body(
            evidence,
            resolutions=[{"item_id": item.id, "returned": 1, "damaged": 1}],
        ),
        format="json",
    )

    assert returned.status_code == 200
    product.refresh_from_db()
    assert product.available_quantity == 2
    assert product.damaged_quantity == 1
    assert product.issued_quantity == 0
    assert product.total_quantity == 3
    loan.request.refresh_from_db()
    assert loan.request.status == HardwareRequest.Status.CLOSED_WITH_ISSUE
    assert RequesterAccountability.objects.filter(
        request=loan.request,
        issue_type=RequesterAccountability.IssueType.DAMAGED,
        quantity=1,
    ).exists()
    # Containerless direct return still records an (immutable) ReturnEvent with a null box.
    event = ReturnEvent.objects.get(request=loan.request)
    assert event.box is None


@override_settings(API_CLIENT_AUTH_REQUIRED=False)
def test_direct_return_rejects_partial_resolution(monkeypatch):
    makerspace = make_space("direct-return-partial")
    admin = make_admin(makerspace)
    product = make_product(makerspace, total_quantity=3, available_quantity=3)
    client = authed(admin)
    client.post(
        direct_url(makerspace),
        direct_payload(items=[{"product_id": product.id, "quantity": 2}]),
        format="json",
    )
    loan = PublicToolLoan.objects.get()
    item = loan.request.items.get()
    evidence = make_return_evidence(makerspace, admin)
    allow_uploaded(monkeypatch)

    response = client.post(
        f"/api/v1/admin/direct-loans/{loan.id}/return",
        return_body(evidence, resolutions=[{"item_id": item.id, "returned": 1}]),
        format="json",
    )

    assert response.status_code == 400
    assert response.data["detail"] == (
        "Direct loan returns must resolve every outstanding unit."
    )
    loan.refresh_from_db()
    assert loan.status == PublicToolLoan.Status.CHECKED_OUT
    product.refresh_from_db()
    assert product.issued_quantity == 2


@override_settings(API_CLIENT_AUTH_REQUIRED=False)
def test_direct_return_individual_asset_outcomes_flip_status_without_double_count(monkeypatch):
    makerspace = make_space("direct-return-individual")
    admin = make_admin(makerspace)
    product = make_product(
        makerspace,
        tracking_mode=TrackingMode.INDIVIDUAL,
        total_quantity=2,
        available_quantity=2,
    )
    asset_a = InventoryAsset.objects.create(
        makerspace=makerspace, product=product, asset_tag="IND-A"
    )
    asset_b = InventoryAsset.objects.create(
        makerspace=makerspace, product=product, asset_tag="IND-B"
    )
    qr_a = make_asset_qr(makerspace, asset_a)
    qr_b = make_asset_qr(makerspace, asset_b)
    client = authed(admin)
    issued = client.post(
        direct_url(makerspace),
        direct_payload(qr_payloads=[qr_a.payload, qr_b.payload]),
        format="json",
    )
    assert issued.status_code == 201
    loan = PublicToolLoan.objects.get()
    item = loan.request.items.get()
    evidence = make_return_evidence(makerspace, admin)
    allow_uploaded(monkeypatch)

    returned = client.post(
        f"/api/v1/admin/direct-loans/{loan.id}/return",
        return_body(
            evidence,
            qr_payload=qr_a.payload,
            resolutions=[
                {
                    "item_id": item.id,
                    "returned": 1,
                    "damaged": 1,
                    "assets": [
                        {"asset_id": asset_a.id, "outcome": "returned"},
                        {"asset_id": asset_b.id, "outcome": "damaged"},
                    ],
                }
            ],
        ),
        format="json",
    )

    assert returned.status_code == 200
    asset_a.refresh_from_db()
    asset_b.refresh_from_db()
    assert asset_a.status == InventoryAsset.Status.AVAILABLE
    assert asset_b.status == InventoryAsset.Status.DAMAGED
    product.refresh_from_db()
    # Buckets moved exactly once (return_items), asset status set directly — no double count.
    assert product.available_quantity == 1
    assert product.damaged_quantity == 1
    assert product.issued_quantity == 0
    assert product.total_quantity == 2


@override_settings(API_CLIENT_AUTH_REQUIRED=False)
def test_direct_return_rejects_duplicate_item_resolutions(monkeypatch):
    # Stage-4 P2: duplicate item_id in resolutions would be applied twice by
    # availability.return_items (over-return). Serializer must reject it.
    makerspace = make_space("direct-return-dup-item")
    admin = make_admin(makerspace)
    product = make_product(makerspace, total_quantity=3, available_quantity=3)
    client = authed(admin)
    client.post(
        direct_url(makerspace),
        direct_payload(items=[{"product_id": product.id, "quantity": 2}]),
        format="json",
    )
    loan = PublicToolLoan.objects.get()
    item = loan.request.items.get()
    evidence = make_return_evidence(makerspace, admin)
    allow_uploaded(monkeypatch)

    response = client.post(
        f"/api/v1/admin/direct-loans/{loan.id}/return",
        return_body(
            evidence,
            resolutions=[
                {"item_id": item.id, "returned": 1},
                {"item_id": item.id, "returned": 1},
            ],
        ),
        format="json",
    )

    assert response.status_code == 400
    loan.refresh_from_db()
    assert loan.status == PublicToolLoan.Status.CHECKED_OUT
    product.refresh_from_db()
    assert product.issued_quantity == 2
