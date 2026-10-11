import pytest
from django.urls import reverse

from apps.audit.models import AuditLog
from apps.hardware_requests.models import HardwareRequest
from apps.inventory.models import InventoryProduct
from apps.makerspaces.capabilities import FEATURES
from apps.makerspaces.module_registry import core_module_keys
from tests.modules.family_helpers import account, client, family_space

pytestmark = pytest.mark.django_db


def test_inventory_only_default_on_account_borrow_and_off_preserves_data():
    space = family_space("family-inventory", loans=True)
    borrower = account("family-borrower")
    product = InventoryProduct.objects.create(makerspace=space, name="Drill", is_public=True,
                                              total_quantity=2, available_quantity=2)
    assert FEATURES["loans.enabled"].default_enabled
    browse = reverse("public-inventory", args=[space.slug])
    submit = reverse("hardware_requests:request-submit", args=[space.slug])
    assert client().get(browse).status_code == 200
    api = client(borrower)
    body = {"items": [{"product_id": product.pk, "quantity": 1}], "requested_for": "Project"}
    response = api.post(submit, body, format="json")
    assert response.status_code == 201, response.data
    request = HardwareRequest.objects.get(makerspace=space)
    assert AuditLog.objects.filter(actor=borrower, action="request.submitted").exists()
    space.enabled_features.remove("loans.enabled")
    space.save(update_fields=["enabled_features"])
    assert client().get(browse).status_code == 400
    assert api.post(submit, body, format="json").status_code == 400
    assert core_module_keys() <= set(space.enabled_modules)
    assert HardwareRequest.objects.filter(pk=request.pk).exists()
    assert InventoryProduct.objects.get(pk=product.pk).available_quantity == 2
    space.enabled_features.append("loans.enabled")
    space.save(update_fields=["enabled_features"])
    assert client().get(browse).status_code == 200



def test_submission_rechecks_loans_under_lock_after_an_unlocked_view_check(monkeypatch):
    from apps.hardware_requests import public_request_views
    from apps.makerspaces.models import Makerspace

    stale_space = family_space("family-loans-disable-race", loans=True)
    borrower = account("family-race-borrower")
    product = InventoryProduct.objects.create(makerspace=stale_space, name="Drill", is_public=True,
        total_quantity=2, available_quantity=2)
    # The view sees its pre-disable row; the creation transaction must read the
    # committed configuration again through select_for_update().
    Makerspace.objects.filter(pk=stale_space.pk).update(enabled_features=[])
    monkeypatch.setattr(public_request_views, "get_public_makerspace", lambda slug: stale_space)
    result = client(borrower).post(reverse("hardware_requests:request-submit", args=[stale_space.slug]),
        {"items": [{"product_id": product.pk, "quantity": 1}], "requested_for": "Project"}, format="json")
    assert result.status_code == 400 and "feature" in result.data
    assert not HardwareRequest.objects.filter(makerspace=stale_space).exists()
    assert not AuditLog.objects.filter(makerspace=stale_space, action="request.submitted").exists()

