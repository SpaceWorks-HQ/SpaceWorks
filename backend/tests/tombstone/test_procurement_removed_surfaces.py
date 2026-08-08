"""apps/procurement under the tombstone profile (plan B5/B6, phase 8).

The pattern `tests/roadmap/test_removed_surfaces.py` established, generalised: prove
the surfaces are gone, and prove the data is not. Every assertion here would pass
trivially if the app had been deleted — what makes them meaningful is that the models,
the migrations and the retention registry are still fully present in this same process.
"""

import pytest
from django.contrib import admin
from django.urls import Resolver404, resolve
from rest_framework.test import APIClient

from apps.machines.low_stock import maybe_flag_low_stock
from apps.makerspaces.models import Makerspace
from apps.makerspaces.module_registry import module_available
from apps.makerspaces.platform import available_modules, bootstrap_payload
from apps.procurement.models import ToBuyItem, ToBuyReceipt
from apps.separability.registry import purge_plan_for, runtime_active
from config.unfold import UNFOLD

pytestmark = pytest.mark.django_db


# --------------------------------------------------------------------------
# Surfaces: gone.
# --------------------------------------------------------------------------

def test_the_app_is_registered_as_inactive():
    assert runtime_active("procurement") is False
    assert module_available("procurement") is False


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/procurement/makerspace/1/to-buy",
        "/api/v1/procurement/to-buy/1",
        "/api/v1/procurement/to-buy/1/receipts",
    ],
)
def test_no_procurement_route_resolves(path):
    with pytest.raises(Resolver404):
        resolve(path)


def test_procurement_endpoints_return_404_rather_than_403():
    """404, not 403: a route that does not exist must not hint that it might."""
    response = APIClient().get("/api/v1/procurement/makerspace/1/to-buy")
    assert response.status_code == 404


def test_the_admin_does_not_register_the_models():
    assert ToBuyItem not in admin.site._registry
    assert ToBuyReceipt not in admin.site._registry


def test_the_sidebar_offers_no_procurement_entry():
    """An entry left behind would raise NoReverseMatch and 500 the whole console."""
    titles = [str(item["title"]) for group in UNFOLD["SIDEBAR"]["navigation"] for item in group["items"]]
    assert "To-buy list" not in titles
    assert all(group["items"] for group in UNFOLD["SIDEBAR"]["navigation"])


def test_the_openapi_schema_does_not_advertise_procurement():
    response = APIClient().get("/schema/?format=json")

    assert response.status_code == 200
    assert b"/api/v1/procurement/" not in response.content


def test_the_bootstrap_payload_omits_the_module():
    space = Makerspace.objects.create(name="tombstoned", slug="tombstoned")
    space.enabled_modules = sorted(set(space.enabled_modules) | {"procurement"})
    space.save(update_fields=["enabled_modules"])

    assert "procurement" not in bootstrap_payload(space)["modules"]
    assert "procurement" not in available_modules(space)


def test_the_low_stock_hook_stops_creating_restock_items():
    """A cross-app write into a module with no screen would grow an unread table.

    The same sequence creates exactly one restock item under the all-active profile
    (`tests/test_b7a_kernel_low_stock.py`), so this asserts the tombstone changed the
    outcome, not that the threshold was never crossed.
    """
    from apps.machines.service_consumable_pools import correct_pool, create_pool
    from tests.return_helpers import make_space, make_user

    space = make_space("tombstone-low-stock")
    actor = make_user("tombstone-low-stock-actor")
    pool = create_pool(
        space, actor, material="PLA", color="Blue", initial_grams="100", low_threshold_grams="50",
    )
    correct_pool(pool, actor, quantity_delta="-60", reason="Calibration usage")

    assert maybe_flag_low_stock(actor, pool) is None
    assert not ToBuyItem.objects.exists()


# --------------------------------------------------------------------------
# Data and retention: untouched.
# --------------------------------------------------------------------------

def test_the_models_still_work():
    """Tombstoning removes surfaces, never rows -- reinstating the app must restore it."""
    space = Makerspace.objects.create(name="retained", slug="retained")
    item = ToBuyItem.objects.create(makerspace=space, name="M3 bolts", quantity=10)

    assert ToBuyItem.objects.get(pk=item.pk).name == "M3 bolts"


def test_the_purge_plan_is_still_registered():
    """Without it, retained receipts stay in the private bucket with nothing naming them."""
    plan = purge_plan_for("procurement")

    assert plan is not None
    assert plan.private_keys is not None


def test_the_migrations_are_still_installed():
    from django.db.migrations.loader import MigrationLoader
    from django.db import connection

    applied = MigrationLoader(connection).applied_migrations

    assert any(app_label == "procurement" for app_label, _ in applied)
