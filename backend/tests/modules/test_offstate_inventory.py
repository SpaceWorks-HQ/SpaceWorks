"""ON/OFF contracts for optional inventory-lifecycle modules.

Each add-on owns a staff surface that must disappear when its key is absent, while
the core catalogue and reviewed-request workflow remain usable. Asset units has one
additional contract: quantity-tracked products are the supported off-state path.
"""

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.inventory.models import InventoryAsset, InventoryProduct, TrackingMode
from apps.makerspaces.models import Makerspace
from apps.makerspaces.module_registry import core_module_keys


pytestmark = pytest.mark.django_db

INVENTORY_ADD_ONS = (
    "containers",
    "asset_units",
    "stock_transfers",
    "stocktake",
    "procurement",
    "bulk_import",
)
CORE_MODULES = frozenset(core_module_keys())


def _space(slug, modules):
    return Makerspace.objects.create(
        name=slug,
        slug=slug,
        enabled_modules=sorted(modules),
        public_inventory_enabled=True,
    )


def _user(slug, *, staff=False):
    return User.objects.create_user(
        username=slug,
        email=f"{slug}@example.test",
        display_name="Inventory module test user",
        role=User.Role.SUPERADMIN if staff else User.Role.REQUESTER,
        is_staff=staff,
        is_superuser=staff,
        access_status=User.AccessStatus.ACTIVE,
    )


def _client(user=None):
    client = APIClient()
    if user is not None:
        client.force_authenticate(user)
    return client


def _product(space, name="Torque wrench", *, quantity=3):
    return InventoryProduct.objects.create(
        makerspace=space,
        name=name,
        total_quantity=quantity,
        available_quantity=quantity,
        is_public=True,
    )


def _exercise_surface(module, space, client):
    """Call the smallest real HTTP surface that proves this module is usable."""
    if module == "containers":
        return client.get(f"/api/v1/admin/makerspace/{space.id}/containers")
    if module == "stock_transfers":
        return client.get(f"/api/v1/admin/makerspace/{space.id}/stock-transfers")
    if module == "stocktake":
        return client.get(f"/api/v1/admin/makerspace/{space.id}/stocktakes")
    if module == "procurement":
        return client.get(f"/api/v1/procurement/makerspace/{space.id}/to-buy")
    if module == "bulk_import":
        return client.post(
            f"/api/v1/admin/makerspace/{space.id}/inventory/import/preview",
            {
                "rows": [
                    {
                        "name": "Safety glasses",
                        "total_quantity": "2",
                        "available_quantity": "2",
                    }
                ]
            },
            format="json",
        )
    if module == "asset_units":
        product = _product(space, name="Unit-tracked drill", quantity=0)
        return client.post(
            f"/api/v1/admin/products/{product.id}/assets/generate",
            {"count": 1},
            format="json",
        )
    raise AssertionError(f"No surface configured for {module}")


@pytest.mark.parametrize("module", INVENTORY_ADD_ONS)
def test_each_inventory_add_on_off_refuses_its_surface_and_on_allows_it(module):
    """The module error must win before business validation or mutation.

    These views use DRF ValidationError for module gates, whose established API shape
    is HTTP 400 with a ``module`` field. The asset assertion additionally proves that
    the rejected mutation did not create hidden unit data.
    """
    off_space = _space(f"inv-off-{module.replace('_', '-')}", CORE_MODULES)
    off_response = _exercise_surface(
        module,
        off_space,
        _client(_user(f"inv-off-staff-{module}", staff=True)),
    )

    assert off_response.status_code == 400
    assert set(off_response.data) == {"module"}
    assert module in str(off_response.data["module"])
    if module == "asset_units":
        assert not InventoryAsset.objects.filter(makerspace=off_space).exists()

    on_space = _space(
        f"inv-on-{module.replace('_', '-')}",
        CORE_MODULES | {module},
    )
    on_response = _exercise_surface(
        module,
        on_space,
        _client(_user(f"inv-on-staff-{module}", staff=True)),
    )

    assert on_response.status_code == (201 if module == "asset_units" else 200)
    if module == "asset_units":
        assert InventoryAsset.objects.filter(makerspace=on_space).count() == 1


def _run_loan_spine(slug, modules):
    """Browse -> submit -> staff queue -> accept -> public status."""
    space = _space(slug, modules)
    product = _product(space)
    requester = _user(f"{slug}-requester")

    catalog = _client().get(reverse("inventory:public-inventory", args=[space.slug]))
    assert catalog.status_code == 200, f"catalog: {catalog.status_code} {catalog.data}"

    submitted = _client(requester).post(
        reverse("hardware_requests:request-submit", args=[space.slug]),
        {
            "requested_for": "Inventory module independence",
            "items": [{"product_id": product.id, "quantity": 1}],
        },
        format="json",
    )
    assert submitted.status_code == 201, (
        f"submit: {submitted.status_code} {submitted.data}"
    )

    staff = _client(_user(f"{slug}-staff", staff=True))
    pending = staff.get(
        reverse("hardware_requests:pending-requests", args=[space.id])
    )
    assert pending.status_code == 200, f"queue: {pending.status_code} {pending.data}"
    assert pending.data["count"] == 1

    accepted = staff.post(
        reverse(
            "hardware_requests:request-accept",
            args=[pending.data["results"][0]["id"]],
        ),
        {},
        format="json",
    )
    assert accepted.status_code == 200, f"accept: {accepted.status_code} {accepted.data}"
    assert accepted.data["status"] == "accepted"

    public_status = _client().get(
        reverse(
            "hardware_requests:request-status",
            args=[submitted.data["public_token"]],
        )
    )
    assert public_status.status_code == 200, (
        f"status: {public_status.status_code} {public_status.data}"
    )
    return product


@pytest.mark.parametrize("missing", INVENTORY_ADD_ONS)
def test_each_inventory_add_on_off_leaves_the_core_loan_spine_working(missing):
    """Removing one inventory add-on cannot leak into the core request workflow."""
    enabled = CORE_MODULES | (set(INVENTORY_ADD_ONS) - {missing})

    _run_loan_spine(f"inv-spine-no-{missing.replace('_', '-')}", enabled)


def test_asset_units_off_uses_plain_quantity_tracking_as_the_substitute():
    """Individual QR units are optional; aggregate stock must remain fully lendable."""
    product = _run_loan_spine("inv-quantity-substitute", CORE_MODULES)

    product.refresh_from_db()
    assert product.tracking_mode == TrackingMode.QUANTITY
    assert product.total_quantity == 3
    assert product.available_quantity == 2
    assert product.reserved_quantity == 1
    assert not product.assets.exists()
