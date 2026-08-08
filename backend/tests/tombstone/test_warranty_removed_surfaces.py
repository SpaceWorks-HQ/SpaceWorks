"""apps/warranty under the tombstone profile (plan B5/B6, phase 10).

Warranty is the case B5 singled out as most exposed, and the reason is that it owns
**no module key**: asset warranties are gated by core `staff_admin` and machine
warranties by `machines`. So the trick that hid procurement and notifications --
dropping a tombstoned app's key from `enabled_modules` -- has nothing to drop here.
`unavailable_apps` exists for exactly this, and the console test below is the one that
would fail if it were removed.

This phase also relocated warranty's staff API out of `admin_api` into the app. The
paths and route names are deliberately unchanged, so `tests/test_warranty.py` still
reverses the same names in the all-active profile; what changed is who owns them, and
therefore whether they can be withdrawn as a unit.
"""

import pytest
from django.contrib import admin
from django.urls import Resolver404, resolve
from rest_framework.test import APIClient

from apps.admin_api.serializers_makerspace_aux import MakerspaceSwitcherSerializer
from apps.makerspaces.models import Makerspace
from apps.separability.registry import runtime_active
from apps.separability.tombstones import unavailable_apps
from apps.warranty.models import Warranty, WarrantyDocument
from config.unfold import UNFOLD

pytestmark = pytest.mark.django_db


# --------------------------------------------------------------------------
# Surfaces: gone.
# --------------------------------------------------------------------------

def test_the_app_is_registered_as_inactive():
    assert runtime_active("warranty") is False


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/admin/assets/1/warranty",
        "/api/v1/admin/machines/1/warranty",
        "/api/v1/admin/warranty/1/documents",
        "/api/v1/admin/warranty/1/documents/presign",
        "/api/v1/admin/warranty/documents/1",
        "/api/v1/admin/warranty/documents/1/url",
        "/api/v1/admin/makerspace/1/warranties",
    ],
)
def test_no_warranty_route_resolves(path):
    with pytest.raises(Resolver404):
        resolve(path)


def test_the_surrounding_admin_api_routes_are_untouched():
    """The relocation withdrew warranty's routes, not its neighbours' on the same prefix."""
    assert resolve("/api/v1/admin/assets/1").url_name == "admin-inventory-asset-detail"
    assert resolve("/api/v1/admin/machines/1/publicity").url_name == "admin-machine-publicity"


def test_the_admin_does_not_register_the_models():
    assert Warranty not in admin.site._registry
    assert WarrantyDocument not in admin.site._registry


def test_the_sidebar_offers_no_warranty_entries():
    titles = [str(item["title"]) for group in UNFOLD["SIDEBAR"]["navigation"] for item in group["items"]]
    assert "Warranties" not in titles
    assert "Warranty documents" not in titles


def test_the_openapi_schema_does_not_advertise_warranty():
    response = APIClient().get("/schema/?format=json")

    assert response.status_code == 200
    assert b"/api/v1/admin/warranty/" not in response.content
    assert b"/warranties" not in response.content


# --------------------------------------------------------------------------
# The console: no module key to drop, so it is told directly.
# --------------------------------------------------------------------------

def test_the_deployment_reports_warranty_as_unavailable():
    assert "warranty" in unavailable_apps()


def test_the_console_payload_names_warranty_so_the_tab_can_be_hidden():
    """`staff_admin` is core and stays enabled, so the module list cannot express this."""
    space = Makerspace.objects.create(name="tombstoned-warranty", slug="tombstoned-warranty")
    data = MakerspaceSwitcherSerializer(space).data

    assert "staff_admin" in data["enabled_modules"]
    assert "warranty" in data["unavailable_apps"]


# --------------------------------------------------------------------------
# Data and retention: untouched.
# --------------------------------------------------------------------------

def test_warranty_rows_are_still_readable():
    warranty = _asset_warranty("retained-warranty")

    assert Warranty.objects.get(pk=warranty.pk).vendor_name == "Acme"


def test_deleting_a_document_still_removes_its_private_object(monkeypatch):
    """Retention: without this receiver a purge leaves private bills in the bucket."""
    from apps.warranty import storage

    deleted = []
    monkeypatch.setattr(storage, "delete_object", deleted.append)

    warranty = _asset_warranty("retained-warranty-doc")
    document = WarrantyDocument.objects.create(
        warranty=warranty,
        object_key="warranty/1/bill.pdf",
        original_filename="bill.pdf",
        content_type="application/pdf",
        size_bytes=10,
    )
    document.delete()

    assert deleted == ["warranty/1/bill.pdf"]



def _asset_warranty(slug):
    """A warranty needs exactly one host (asset XOR machine), enforced by a check constraint."""
    from apps.inventory.models import InventoryAsset, InventoryProduct
    from tests.return_helpers import make_space

    space = make_space(slug)
    product = InventoryProduct.objects.create(makerspace=space, name="Widget", total_quantity=1)
    asset = InventoryAsset.objects.create(
        makerspace=space, product=product, asset_tag=f"{slug}-1", serial_number=f"{slug}-sn"
    )
    return Warranty.objects.create(makerspace=space, asset=asset, vendor_name="Acme")
