import pytest
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.apiclients.models import ApiClient
from apps.boxes.models import QrCode, QrScanEvent
from apps.inventory.models import TrackingMode
from apps.presence import services as presence
from tests.return_helpers import authenticated_client, make_issue_evidence, make_member, make_product, make_space, make_user

pytestmark = pytest.mark.django_db


def test_public_inventory_detail_uses_safe_serializer_only():
    makerspace = make_space("prd-detail")
    product = make_product(makerspace, storage_location="Secret shelf")

    response = APIClient().get(f"/api/v1/public/{makerspace.slug}/inventory/{product.id}/")

    assert response.status_code == 200
    assert response.data["name"] == product.name
    assert "storage_location" not in response.data
    assert "box" not in response.data


def test_qr_resolve_records_lookup_and_returns_allowed_actions():
    makerspace = make_space("prd-scanner")
    makerspace.enabled_modules = ["scanner", "self_checkout", "qr_management"]
    makerspace.save(update_fields=["enabled_modules"])
    manager = make_member("prd-scanner-manager", makerspace)
    product = make_product(makerspace, public_self_checkout_enabled=True)
    qr = QrCode.objects.create(
        makerspace=makerspace,
        target_type=QrCode.TargetType.PRODUCT,
        target_id=product.id,
    )

    response = authenticated_client(manager).post(
        "/api/v1/admin/qr/resolve",
        {"payload": qr.payload},
        format="json",
    )

    assert response.status_code == 200
    assert response.data["target"]["type"] == "product"
    assert "checkout" in response.data["allowed_actions"]
    assert "revoke" in response.data["allowed_actions"]
    assert QrScanEvent.objects.filter(context=QrScanEvent.Context.SCANNER_LOOKUP).count() == 1


def test_browser_api_client_rejects_admin_write_scope():
    makerspace = make_space("prd-client")
    # Issuance is superadmin-only now; use a superadmin so we reach the serializer's
    # scope validation (the browser+admin:write rejection) rather than the 403 gate.
    superadmin = make_user(
        "prd-client-superadmin",
        role=User.Role.SUPERADMIN,
        is_superuser=True,
    )

    response = authenticated_client(superadmin).post(
        f"/api/v1/admin/makerspace/{makerspace.id}/api-clients",
        {
            "label": "Public browser",
            "client_type": "browser",
            "allowed_origins": ["https://example.test"],
            "scopes": ["admin:write"],
        },
        format="json",
    )

    assert response.status_code == 400


def test_api_client_scope_metadata_is_persisted():
    makerspace = make_space("prd-client-scope")
    client, _secret = ApiClient.issue(
        label="Reports",
        makerspace=makerspace,
        allowed_origins=["https://reports.test"],
        client_type="server",
        scopes=["public:read"],
        rate_limit_tier="trusted",
    )

    assert client.client_type == "server"
    assert client.scopes == ["public:read"]
    assert client.rate_limit_tier == "trusted"


def test_individual_mode_manual_direct_handout_requires_asset_scan():
    makerspace = make_space("prd-serialized-handout")
    manager = make_member("prd-serialized-manager", makerspace)
    borrower = make_member("prd-serialized-borrower", makerspace)
    presence.start_session(borrower, makerspace, 60)
    product = make_product(
        makerspace,
        tracking_mode=TrackingMode.INDIVIDUAL,
        public_self_checkout_enabled=True,
    )

    response = authenticated_client(manager).post(
        f"/api/v1/admin/makerspace/{makerspace.id}/direct-loans",
        {
            "borrower_id": borrower.id,
            "evidence_id": make_issue_evidence(makerspace, manager).id,
            "items": [{"product_id": product.id, "quantity": 1}],
        },
        format="json",
    )

    assert response.status_code == 400
    assert "asset QR" in str(response.data)
