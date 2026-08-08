import pytest

from apps.accounts.models import User
from apps.boxes.models import QrCode, QrScanEvent
from apps.inventory.models import InventoryAsset, TrackingMode
from apps.makerspaces.models import MakerspaceMembership
from apps.operations import services
from apps.operations.models import StocktakeLine, StocktakeSession
from tests.return_helpers import authenticated_client, make_box, make_member, make_product, make_space, make_user
from tests.handout_roles import make_handout_member

pytestmark = pytest.mark.django_db


def _qr(makerspace, target_type, target_id, actor, payload=None):
    return QrCode.objects.create(
        makerspace=makerspace,
        payload=payload or f"stocktake-{target_type}-{target_id}",
        target_type=target_type,
        target_id=target_id,
        created_by=actor,
    )


def _setup_stocktake_scan():
    makerspace = make_space("stocktake-scan")
    manager = make_member(
        "stocktake-scan-manager",
        makerspace,
        membership_role=MakerspaceMembership.Role.INVENTORY_MANAGER,
        role=User.Role.REQUESTER,
    )
    stocktake = StocktakeSession.objects.create(makerspace=makerspace, started_by=manager)
    product = make_product(makerspace, name="Calipers", total_quantity=5, available_quantity=5)
    asset_product = make_product(
        makerspace,
        name="Serialized Scope",
        tracking_mode=TrackingMode.INDIVIDUAL,
        total_quantity=1,
        available_quantity=1,
    )
    asset = InventoryAsset.objects.create(
        makerspace=makerspace,
        product=asset_product,
        asset_tag="SCOPE-001",
        status=InventoryAsset.Status.AVAILABLE,
    )
    box = make_box(makerspace, "Stocktake Tote")
    return {
        "makerspace": makerspace,
        "manager": manager,
        "stocktake": stocktake,
        "product": product,
        "asset": asset,
        "box": box,
        "product_qr": _qr(makerspace, QrCode.TargetType.PRODUCT, product.id, manager),
        "asset_qr": _qr(makerspace, QrCode.TargetType.ASSET, asset.id, manager),
        "box_qr": _qr(makerspace, QrCode.TargetType.BOX, box.id, manager, payload=box.code),
    }


def _resolve(client, stocktake, payload):
    return client.post(
        f"/api/v1/admin/stocktakes/{stocktake.id}/resolve-scan",
        {"payload": payload},
        format="json",
    )


def test_stocktake_resolve_scan_returns_product_asset_and_box_targets():
    data = _setup_stocktake_scan()
    client = authenticated_client(data["manager"])

    product = _resolve(client, data["stocktake"], data["product_qr"].payload)
    asset = _resolve(client, data["stocktake"], data["asset_qr"].payload)
    box = _resolve(client, data["stocktake"], data["box_qr"].payload)

    assert product.status_code == 200
    assert product.data["type"] == "product"
    assert product.data["product_id"] == data["product"].id
    assert asset.status_code == 200
    assert asset.data["type"] == "asset"
    assert asset.data["asset_id"] == data["asset"].id
    assert asset.data["product_id"] == data["asset"].product_id
    assert box.status_code == 200
    assert box.data["type"] == "box"
    assert box.data["container_id"] == data["box"].id
    assert QrScanEvent.objects.count() == 0


def test_stocktake_resolve_scan_rejects_cross_makerspace_qr():
    data = _setup_stocktake_scan()
    other = make_space("stocktake-scan-other")
    superadmin = make_user(
        "stocktake-scan-super",
        role=User.Role.SUPERADMIN,
        access_status=User.AccessStatus.ACTIVE,
    )
    foreign_product = make_product(other, name="Foreign Calipers")
    foreign_qr = _qr(other, QrCode.TargetType.PRODUCT, foreign_product.id, superadmin)

    response = _resolve(authenticated_client(superadmin), data["stocktake"], foreign_qr.payload)

    assert response.status_code in {400, 404}
    if response.status_code == 400:
        assert "different makerspace" in str(response.data)


def test_stocktake_resolve_scan_requires_edit_inventory_and_known_payload():
    data = _setup_stocktake_scan()
    guest = make_handout_member("stocktake-scan-guest", data["makerspace"])

    denied = _resolve(authenticated_client(guest), data["stocktake"], data["product_qr"].payload)
    missing = _resolve(authenticated_client(data["manager"]), data["stocktake"], "missing-payload")

    assert denied.status_code in {403, 404}
    assert missing.status_code == 404


def test_stocktake_scan_result_reuses_add_stocktake_line_for_count_mutation():
    data = _setup_stocktake_scan()
    resolved = services.resolve_scan_target(data["manager"], data["stocktake"], data["product_qr"].payload)

    line = services.add_stocktake_line(
        data["manager"],
        data["stocktake"],
        {
            "product_id": resolved["product_id"],
            "counted_quantity": 3,
            "condition": StocktakeLine.Condition.AVAILABLE,
        },
    )

    assert StocktakeLine.objects.filter(stocktake=data["stocktake"]).count() == 1
    assert line.product_id == data["product"].id
    assert line.expected_quantity == 5
    assert line.counted_quantity == 3
    assert line.variance_quantity == -2