import pytest
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.boxes.models import Box
from apps.inventory.models import InventoryAsset, InventoryProduct, TrackingMode
from apps.makerspaces.models import Makerspace, MakerspaceMembership
from tests.handout_roles import make_handout_member

pytestmark = pytest.mark.django_db


def make_space(slug="asset-editor-space"):
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


def make_guest(makerspace):
    return make_handout_member(f"guest-{makerspace.slug}", makerspace)


def authed(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def make_product(makerspace, **overrides):
    defaults = {
        "makerspace": makerspace,
        "name": "Bench Multimeter",
        "tracking_mode": TrackingMode.INDIVIDUAL,
        "total_quantity": 1,
        "available_quantity": 1,
    }
    defaults.update(overrides)
    return InventoryProduct.objects.create(**defaults)


def make_asset(makerspace, *, product=None, tag="ASSET-1", **overrides):
    defaults = {
        "makerspace": makerspace,
        "product": product or make_product(makerspace),
        "asset_tag": tag,
    }
    defaults.update(overrides)
    return InventoryAsset.objects.create(**defaults)


def asset_url(asset):
    return f"/api/v1/admin/assets/{asset.id}"


def test_patch_updates_individual_asset_fields_and_audits():
    makerspace = make_space("asset-editor-happy")
    admin = make_admin(makerspace)
    old_box = Box.objects.create(makerspace=makerspace, label="Old shelf")
    new_box = Box.objects.create(makerspace=makerspace, label="New shelf")
    asset = make_asset(
        makerspace,
        tag="OLD-1",
        box=old_box,
        serial_number="SN-OLD",
        notes="old notes",
        public_self_checkout_enabled=False,
    )

    response = authed(admin).patch(
        asset_url(asset),
        {
            "asset_tag": "NEW-1",
            "serial_number": "SN-NEW",
            "box": new_box.id,
            "notes": "calibrated and ready",
            "public_self_checkout_enabled": True,
        },
        format="json",
    )

    assert response.status_code == 200
    asset.refresh_from_db()
    assert asset.asset_tag == "NEW-1"
    assert asset.serial_number == "SN-NEW"
    assert asset.box_id == new_box.id
    assert asset.notes == "calibrated and ready"
    assert asset.public_self_checkout_enabled is True
    assert response.data["public_self_checkout_enabled"] is True
    audit = AuditLog.objects.get(action="inventory.asset_updated")
    assert audit.makerspace_id == makerspace.id
    assert audit.target_type == "inventory.inventoryasset"
    assert audit.target_id == str(asset.id)
    assert audit.meta == {
        "product_id": asset.product_id,
        "fields": [
            "asset_tag",
            "box",
            "notes",
            "public_self_checkout_enabled",
            "serial_number",
        ],
    }


def test_patch_ignores_status_field():
    makerspace = make_space("asset-editor-status-ignore")
    admin = make_admin(makerspace)
    asset = make_asset(makerspace, tag="STATUS-1")

    response = authed(admin).patch(
        asset_url(asset),
        {"status": InventoryAsset.Status.LOST, "notes": "metadata only"},
        format="json",
    )

    assert response.status_code == 200
    asset.refresh_from_db()
    assert asset.status == InventoryAsset.Status.AVAILABLE
    assert asset.notes == "metadata only"


@pytest.mark.parametrize(
    "status",
    [InventoryAsset.Status.ISSUED, InventoryAsset.Status.RESERVED],
)
def test_patch_rejects_asset_mid_loan(status):
    makerspace = make_space(f"asset-editor-{status}")
    admin = make_admin(makerspace)
    asset = make_asset(makerspace, tag=f"MID-{status}", status=status)

    response = authed(admin).patch(
        asset_url(asset),
        {"notes": "should not update"},
        format="json",
    )

    assert response.status_code == 400
    asset.refresh_from_db()
    assert asset.notes == ""


def test_patch_rejects_duplicate_asset_tag_in_same_makerspace():
    makerspace = make_space("asset-editor-duplicate")
    admin = make_admin(makerspace)
    make_asset(makerspace, tag="DUP-1")
    asset = make_asset(makerspace, tag="DUP-2")

    response = authed(admin).patch(
        asset_url(asset),
        {"asset_tag": "DUP-1"},
        format="json",
    )

    assert response.status_code == 400
    assert "asset_tag" in response.data
    asset.refresh_from_db()
    assert asset.asset_tag == "DUP-2"


def test_patch_rejects_box_from_another_makerspace():
    makerspace = make_space("asset-editor-box-a")
    other = make_space("asset-editor-box-b")
    admin = make_admin(makerspace)
    other_box = Box.objects.create(makerspace=other, label="Other shelf")
    asset = make_asset(makerspace, tag="BOX-1")

    response = authed(admin).patch(
        asset_url(asset),
        {"box": other_box.id},
        format="json",
    )

    assert response.status_code == 400
    assert response.data["box"] == ["Container is not in this makerspace."]
    asset.refresh_from_db()
    assert asset.box_id is None


def test_patch_hides_cross_tenant_asset():
    makerspace = make_space("asset-editor-primary")
    other = make_space("asset-editor-other")
    admin = make_admin(makerspace)
    asset = make_asset(other, tag="OTHER-1")

    response = authed(admin).patch(
        asset_url(asset),
        {"notes": "cross tenant"},
        format="json",
    )

    assert response.status_code == 404
    asset.refresh_from_db()
    assert asset.notes == ""


def test_patch_same_tenant_wrong_role_is_forbidden():
    makerspace = make_space("asset-editor-wrong-role")
    guest = make_guest(makerspace)
    asset = make_asset(makerspace, tag="ROLE-1")

    response = authed(guest).patch(
        asset_url(asset),
        {"notes": "guest edit"},
        format="json",
    )

    assert response.status_code == 403
    asset.refresh_from_db()
    assert asset.notes == ""


def test_patch_asset_from_tenant_branded_origin_is_allowed():
    # Stage-4: the origin-scope guard must resolve the asset <pk> route to its
    # makerspace for tenant-branded staff domains, else legitimate PATCHes 403.
    makerspace = make_space("asset-editor-origin")
    makerspace.frontend_domain = "tools.example.org"
    makerspace.frontend_domain_status = Makerspace.DomainStatus.VERIFIED
    makerspace.save(update_fields=["frontend_domain", "frontend_domain_status"])
    admin = make_admin(makerspace)
    asset = make_asset(makerspace, tag="ORIGIN-1")

    response = authed(admin).patch(
        asset_url(asset),
        {"notes": "scoped via origin"},
        format="json",
        HTTP_ORIGIN="https://tools.example.org",
    )

    assert response.status_code == 200
    asset.refresh_from_db()
    assert asset.notes == "scoped via origin"
