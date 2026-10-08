"""The managed `assets` fair-use cap refuses a QR asset batch that would cross it.

`services_qr_assets.generate_assets_with_qr` checks the quota inside its transaction
before creating units; the 2026-10-09 audit found the call site had no test.
"""

import pytest
from django.test import override_settings
from rest_framework.exceptions import ValidationError

from apps.inventory.models import InventoryAsset
from apps.operations.services_qr_assets import generate_assets_with_qr
from tests.return_helpers import make_member, make_product, make_space

pytestmark = pytest.mark.django_db


def _setup(slug, cap):
    space = make_space(slug)
    space.resource_limit_overrides = {"assets": cap}
    space.save(update_fields=["resource_limit_overrides"])
    return space, make_member(f"{slug}-manager", space), make_product(space, name=f"{slug} drill")


@override_settings(PLATFORM_DOMAIN_SUFFIX=".space-works.tech")
def test_managed_asset_batch_past_the_cap_is_refused_whole():
    space, manager, product = _setup("asset-quota-managed", 2)

    with pytest.raises(ValidationError) as exc_info:
        generate_assets_with_qr(manager, product, {"count": 3})

    assert "limit" in exc_info.value.detail
    assert InventoryAsset.objects.filter(makerspace=space).count() == 0
    generate_assets_with_qr(manager, product, {"count": 2})
    assert InventoryAsset.objects.filter(makerspace=space).count() == 2


@override_settings(PLATFORM_DOMAIN_SUFFIX="")
def test_self_host_ignores_the_asset_cap():
    space, manager, product = _setup("asset-quota-self", 1)

    generate_assets_with_qr(manager, product, {"count": 3})

    assert InventoryAsset.objects.filter(makerspace=space).count() == 3
