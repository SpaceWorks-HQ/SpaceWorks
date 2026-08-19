from unittest.mock import Mock

import pytest
from django.test import override_settings
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.boxes.models import Box, QrCode, QrScanEvent
from apps.evidence.models import EvidencePhoto
from apps.evidence.storage import EvidenceValidationResult
from apps.hardware_requests.models import HardwareRequest, PublicToolLoan
from apps.inventory.models import InventoryAsset, InventoryProduct, TrackingMode
from apps.makerspaces.models import Makerspace, MakerspaceMembership, MakerspaceRole
from apps.presence import services as presence

pytestmark = pytest.mark.django_db

def make_space(slug="self-checkout-space"):
    return Makerspace.objects.create(name=slug, slug=slug)


def make_product(makerspace, **overrides):
    defaults = {
        "makerspace": makerspace,
        "name": "USB Logic Analyzer",
        "total_quantity": 2,
        "available_quantity": 2,
        "is_public": True,
        "is_archived": False,
    }
    defaults.update(overrides)
    return InventoryProduct.objects.create(**defaults)


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


def eligible_member(makerspace, username="member-1"):
    user = User.objects.create_user(
        username=username,
        email=f"{username}@example.com",
        phone="+15550101010",
        display_name="Self Checkout",
    )
    MakerspaceMembership.objects.create(
        makerspace=makerspace,
        user=user,
        role=MakerspaceMembership.Role.CUSTOM,
        assigned_role=MakerspaceRole.objects.get(makerspace=makerspace, slug="member"),
    )
    presence.start_session(user, makerspace, 60)
    return user


def member_client(user):
    client = APIClient(REMOTE_ADDR="10.20.30.40")
    client.force_authenticate(user)
    return client


def checkout_url(makerspace):
    return f"/api/v1/public/{makerspace.slug}/tools/checkout"


def return_url(makerspace):
    return f"/api/v1/public/{makerspace.slug}/tools/return"


def evidence_url(makerspace):
    return f"/api/v1/public/{makerspace.slug}/tools/evidence-url"


def checkout_payload(makerspace, user, payload, **overrides):
    body = {
        "payload": payload,
    }
    body.update(overrides)
    if "evidence_id" not in body:
        body["evidence_id"] = public_evidence(makerspace, user, EvidencePhoto.EvidenceType.ISSUE).id
    return body


def return_payload(makerspace, user, payload, remark="Returned in good condition.", **overrides):
    body = {
        "payload": payload,
        "remark": remark,
        "evidence_id": public_evidence(makerspace, user, EvidencePhoto.EvidenceType.RETURN).id,
    }
    body.update(overrides)
    return body


def public_evidence(makerspace, user, evidence_type):
    return EvidencePhoto.objects.create(
        makerspace=makerspace,
        evidence_type=evidence_type,
        object_key=f"evidence/{makerspace.id}/{evidence_type}/{user.id}-{EvidencePhoto.objects.count() + 1}",
        uploaded_by=user,
    )

@override_settings(API_CLIENT_AUTH_REQUIRED=False)
def test_public_checkout_requires_tool_opt_in():
    makerspace = make_space("checkout-disabled")
    user = eligible_member(makerspace)
    product = make_product(makerspace, public_self_checkout_enabled=False)
    qr = make_qr(makerspace, product)

    response = member_client(user).post(
        checkout_url(makerspace),
        checkout_payload(makerspace, user, qr.payload),
        format="json",
    )

    assert response.status_code == 400
    assert HardwareRequest.objects.count() == 0
    product.refresh_from_db()
    assert product.available_quantity == 2
    assert product.issued_quantity == 0


@override_settings(API_CLIENT_AUTH_REQUIRED=False)
def test_public_checkout_requires_public_self_checkout_flags():
    makerspace = make_space("checkout-private")
    user = eligible_member(makerspace)
    product = make_product(
        makerspace,
        is_public=False,
        public_self_checkout_enabled=False,
    )
    qr = make_qr(makerspace, product)

    response = member_client(user).post(
        checkout_url(makerspace),
        checkout_payload(makerspace, user, qr.payload),
        format="json",
    )

    assert response.status_code == 400
    assert response.data["detail"] == "Tool is not enabled for public self-checkout."
    assert HardwareRequest.objects.count() == 0
    product.refresh_from_db()
    assert product.available_quantity == 2
    assert product.issued_quantity == 0


@override_settings(API_CLIENT_AUTH_REQUIRED=False)
def test_public_checkout_requires_issue_evidence():
    makerspace = make_space("checkout-missing-evidence")
    user = eligible_member(makerspace)
    product = make_product(makerspace, public_self_checkout_enabled=True)
    qr = make_qr(makerspace, product)
    payload = checkout_payload(makerspace, user, qr.payload)
    payload.pop("evidence_id")

    response = member_client(user).post(
        checkout_url(makerspace),
        payload,
        format="json",
    )

    assert response.status_code == 400
    assert "evidence_id" in response.data
    assert HardwareRequest.objects.count() == 0


@override_settings(API_CLIENT_AUTH_REQUIRED=False)
def test_public_checkout_rejects_product_qr_for_individual_tracked_product():
    makerspace = make_space("checkout-individual-product-qr")
    user = eligible_member(makerspace)
    product = make_product(
        makerspace,
        public_self_checkout_enabled=True,
        tracking_mode=TrackingMode.INDIVIDUAL,
    )
    qr = make_qr(makerspace, product)

    response = member_client(user).post(
        checkout_url(makerspace),
        checkout_payload(makerspace, user, qr.payload),
        format="json",
    )

    assert response.status_code == 400
    assert response.data["detail"] == (
        "Individual-tracked products require a scanned asset QR."
    )
    assert HardwareRequest.objects.count() == 0
    product.refresh_from_db()
    assert product.available_quantity == 2
    assert product.issued_quantity == 0


@override_settings(API_CLIENT_AUTH_REQUIRED=False)
def test_public_checkout_accepts_asset_qr_for_individual_tracked_product():
    makerspace = make_space("checkout-individual-asset-qr")
    user = eligible_member(makerspace)
    product = make_product(
        makerspace,
        public_self_checkout_enabled=True,
        tracking_mode=TrackingMode.INDIVIDUAL,
        total_quantity=1,
        available_quantity=1,
    )
    asset = InventoryAsset.objects.create(
        makerspace=makerspace,
        product=product,
        asset_tag="IND-PUBLIC-1",
        public_self_checkout_enabled=True,
    )
    qr = make_asset_qr(makerspace, asset)

    response = member_client(user).post(
        checkout_url(makerspace),
        checkout_payload(makerspace, user, qr.payload),
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
def test_public_checkout_rejects_box_qr_fallback_for_individual_tracked_product():
    makerspace = make_space("checkout-individual-box")
    user = eligible_member(makerspace)
    box = Box.objects.create(makerspace=makerspace, label="Individual shelf")
    product = make_product(
        makerspace,
        box=box,
        public_self_checkout_enabled=True,
        tracking_mode=TrackingMode.INDIVIDUAL,
        total_quantity=1,
        available_quantity=1,
    )
    qr = QrCode.objects.create(
        makerspace=makerspace,
        target_type=QrCode.TargetType.BOX,
        target_id=box.id,
    )

    response = member_client(user).post(
        checkout_url(makerspace),
        checkout_payload(makerspace, user, qr.payload),
        format="json",
    )

    assert response.status_code == 400
    assert response.data["detail"] == (
        "Individual-tracked products require a scanned asset QR."
    )
    assert HardwareRequest.objects.count() == 0
    product.refresh_from_db()
    assert product.available_quantity == 1
    assert product.issued_quantity == 0


@override_settings(API_CLIENT_AUTH_REQUIRED=False)
def test_public_checkout_and_return_move_inventory_and_record_scans(
    monkeypatch, settings
):
    settings.STORAGE_PRESIGN_METHOD = "post"
    finalize = Mock(
        side_effect=lambda evidence, max_bytes: EvidenceValidationResult(
            size=123, content_type="image/png"
        )
    )
    monkeypatch.setattr("apps.evidence.storage.finalize_upload", finalize)
    makerspace = make_space("checkout-return")
    user = eligible_member(makerspace)
    product = make_product(makerspace, public_self_checkout_enabled=True)
    qr = make_qr(makerspace, product)
    client = member_client(user)

    checkout = client.post(
        checkout_url(makerspace),
        checkout_payload(makerspace, user, qr.payload),
        format="json",
    )

    assert checkout.status_code == 201
    assert checkout.data["status"] == PublicToolLoan.Status.CHECKED_OUT
    assert checkout.data["items"] == [
        {"product_name": "USB Logic Analyzer", "quantity": 1}
    ]
    product.refresh_from_db()
    assert product.available_quantity == 1
    assert product.issued_quantity == 1
    request = HardwareRequest.objects.get()
    assert request.status == HardwareRequest.Status.ISSUED
    assert request.requester_name == user.display_name
    assert request.requester_contact_email == user.email
    assert request.requester_contact_phone == "+15550101010"
    loan = PublicToolLoan.objects.get()
    assert request.return_due_at == loan.due_at
    assert QrScanEvent.objects.get(context=QrScanEvent.Context.ISSUE).request == request

    returned = client.post(
        return_url(makerspace),
        return_payload(makerspace, user, qr.payload),
        format="json",
    )

    assert returned.status_code == 200
    assert returned.data["status"] == PublicToolLoan.Status.RETURNED
    product.refresh_from_db()
    assert product.available_quantity == 2
    assert product.issued_quantity == 0
    request.refresh_from_db()
    assert request.status == HardwareRequest.Status.RETURNED
    assert QrScanEvent.objects.filter(context=QrScanEvent.Context.RETURN).count() == 1
    loan.refresh_from_db()
    assert [call.args[0] for call in finalize.call_args_list] == [
        request.issue_evidence,
        loan.return_evidence,
    ]
    assert all(
        call.args[1] == settings.EVIDENCE_MAX_BYTES
        for call in finalize.call_args_list
    )


@override_settings(API_CLIENT_AUTH_REQUIRED=False)
def test_public_box_checkout_return_restores_all_items():
    makerspace = make_space("checkout-return-box")
    user = eligible_member(makerspace)
    box = Box.objects.create(makerspace=makerspace, label="Loan shelf")
    product_a = make_product(
        makerspace,
        name="Logic Analyzer",
        box=box,
        public_self_checkout_enabled=True,
    )
    product_b = make_product(
        makerspace,
        name="Oscilloscope Probe",
        box=box,
        public_self_checkout_enabled=True,
    )
    qr = QrCode.objects.create(
        makerspace=makerspace,
        target_type=QrCode.TargetType.BOX,
        target_id=box.id,
    )
    client = member_client(user)

    checkout = client.post(
        checkout_url(makerspace),
        checkout_payload(makerspace, user, qr.payload),
        format="json",
    )

    assert checkout.status_code == 201
    assert sorted(item["product_name"] for item in checkout.data["items"]) == [
        "Logic Analyzer",
        "Oscilloscope Probe",
    ]
    product_a.refresh_from_db()
    product_b.refresh_from_db()
    assert product_a.available_quantity == 1
    assert product_a.issued_quantity == 1
    assert product_b.available_quantity == 1
    assert product_b.issued_quantity == 1

    returned = client.post(
        return_url(makerspace),
        return_payload(makerspace, user, qr.payload),
        format="json",
    )

    assert returned.status_code == 200
    product_a.refresh_from_db()
    product_b.refresh_from_db()
    assert product_a.available_quantity == 2
    assert product_a.issued_quantity == 0
    assert product_b.available_quantity == 2
    assert product_b.issued_quantity == 0


@override_settings(API_CLIENT_AUTH_REQUIRED=False)
def test_public_return_requires_same_verified_user():
    makerspace = make_space("checkout-other-user")
    user = eligible_member(makerspace)
    other_user = eligible_member(makerspace, "member-2")
    product = make_product(makerspace, public_self_checkout_enabled=True)
    qr = make_qr(makerspace, product)
    client = member_client(user)
    client.post(
        checkout_url(makerspace),
        checkout_payload(makerspace, user, qr.payload),
        format="json",
    )

    response = member_client(other_user).post(
        return_url(makerspace),
        return_payload(makerspace, other_user, qr.payload),
        format="json",
    )

    assert response.status_code == 403
    assert response.data["code"] == "requester_blocked"
    assert PublicToolLoan.objects.get().status == PublicToolLoan.Status.CHECKED_OUT




@override_settings(API_CLIENT_AUTH_REQUIRED=False)
def test_public_self_checkout_evidence_upload_url_is_audited(monkeypatch):
    makerspace = make_space("checkout-evidence-audit")
    user = eligible_member(makerspace)
    monkeypatch.setattr(
        "apps.hardware_requests.self_checkout_views.presigned_upload",
        lambda object_key, content_type: {"url": "https://storage.test/upload", "fields": {"key": object_key}},
    )

    response = member_client(user).post(
        evidence_url(makerspace),
        {
            "evidence_type": EvidencePhoto.EvidenceType.ISSUE,
            "content_type": "image/png",
            "size_bytes": 4321,
        },
        format="json",
    )

    assert response.status_code == 201
    photo = EvidencePhoto.objects.get(pk=response.data["evidence_id"])
    assert photo.content_type == "image/png"
    assert photo.size_bytes == 4321
    event = AuditLog.objects.get(action="evidence.upload_url_issued")
    assert event.makerspace == makerspace
    assert event.actor == photo.uploaded_by
    assert event.target_type == "evidence.evidencephoto"
    assert event.target_id == str(photo.id)
    assert event.meta == {"surface": "public_self_checkout", "type": EvidencePhoto.EvidenceType.ISSUE}


# --- Phase 5: public report-a-problem (one-tap return stays unchanged) ---


@override_settings(API_CLIENT_AUTH_REQUIRED=False)
def test_public_return_report_problem_creates_report_and_keeps_stock_available():
    from apps.hardware_requests.models import PublicProblemReport

    makerspace = make_space("checkout-report")
    user = eligible_member(makerspace)
    product = make_product(makerspace, public_self_checkout_enabled=True)
    qr = make_qr(makerspace, product)
    client = member_client(user)
    checkout = client.post(checkout_url(makerspace), checkout_payload(makerspace, user, qr.payload), format="json")
    assert checkout.status_code == 201

    returned = client.post(
        return_url(makerspace),
        return_payload(makerspace, user, qr.payload, report_problem=True, problem_note="Tip is bent."),
        format="json",
    )

    assert returned.status_code == 200
    assert returned.data["status"] == PublicToolLoan.Status.RETURNED
    product.refresh_from_db()
    # Public users never classify damage — stock returns to available, flagged for staff.
    assert product.available_quantity == 2
    assert product.damaged_quantity == 0
    report = PublicProblemReport.objects.get()
    assert report.note == "Tip is bent."
    assert report.makerspace == makerspace
    assert report.resolved_at is None
    assert AuditLog.objects.filter(action="public_tool.problem_reported").exists()


@override_settings(API_CLIENT_AUTH_REQUIRED=False)
def test_public_return_without_report_creates_no_problem_report():
    from apps.hardware_requests.models import PublicProblemReport

    makerspace = make_space("checkout-no-report")
    user = eligible_member(makerspace)
    product = make_product(makerspace, public_self_checkout_enabled=True)
    qr = make_qr(makerspace, product)
    client = member_client(user)
    client.post(checkout_url(makerspace), checkout_payload(makerspace, user, qr.payload), format="json")

    returned = client.post(return_url(makerspace), return_payload(makerspace, user, qr.payload), format="json")

    assert returned.status_code == 200
    assert not PublicProblemReport.objects.exists()


@override_settings(API_CLIENT_AUTH_REQUIRED=False)
def test_public_return_report_problem_requires_note():
    makerspace = make_space("checkout-report-note")
    user = eligible_member(makerspace)
    product = make_product(makerspace, public_self_checkout_enabled=True)
    qr = make_qr(makerspace, product)
    client = member_client(user)
    client.post(checkout_url(makerspace), checkout_payload(makerspace, user, qr.payload), format="json")

    response = client.post(
        return_url(makerspace),
        return_payload(makerspace, user, qr.payload, report_problem=True, problem_note="   "),
        format="json",
    )

    assert response.status_code == 400
