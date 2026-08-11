from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.hardware_requests.models import HardwareRequest, HardwareRequestItem
from apps.inventory.models import InventoryProduct
from apps.makerspaces.models import Makerspace, MakerspaceMembership


pytestmark = pytest.mark.django_db


@pytest.fixture
def current_loan():
    makerspace = Makerspace.objects.create(
        name="Holder privacy lab",
        slug="holder-privacy-lab",
        public_inventory_enabled=True,
        public_stats_enabled=True,
    )
    borrower = User.objects.create_user(
        username="holder-privacy-borrower",
        email="holder-privacy@example.com",
    )
    issued_at = timezone.now().replace(microsecond=0) - timedelta(days=1)
    due_at = issued_at + timedelta(days=7)
    request = HardwareRequest.objects.create(
        makerspace=makerspace,
        requester=borrower,
        requester_username=borrower.username,
        requester_name="Real Borrower",
        status=HardwareRequest.Status.ISSUED,
        issued_at=issued_at,
        return_due_at=due_at,
    )
    product = InventoryProduct.objects.create(
        makerspace=makerspace,
        name="Thermal Camera",
        total_quantity=1,
        issued_quantity=1,
        is_public=True,
    )
    HardwareRequestItem.objects.create(
        request=request,
        product=product,
        requested_quantity=1,
        accepted_quantity=1,
        issued_quantity=1,
    )
    url = reverse(
        "v1:public-makerspace-stats",
        kwargs={"makerspace_slug": makerspace.slug},
    )
    return makerspace, url


def _loan_row(response):
    assert response.status_code == 200
    assert len(response.data["current_loans"]) == 1
    return response.data["current_loans"][0]


def test_public_stats_shows_real_holder_name_when_enabled(current_loan):
    makerspace, url = current_loan
    makerspace.public_stats_show_holder_names = True
    makerspace.save(update_fields=["public_stats_show_holder_names"])

    row = _loan_row(APIClient().get(url))

    assert row["holder_name"] == "Real Borrower"


def test_public_stats_uses_generic_holder_name_when_disabled(current_loan):
    _makerspace, url = current_loan

    row = _loan_row(APIClient().get(url))

    assert row["holder_name"] == "Member"


def test_disabling_holder_names_preserves_current_loan_shape_and_dates(current_loan):
    makerspace, url = current_loan
    makerspace.public_stats_show_holder_names = True
    makerspace.save(update_fields=["public_stats_show_holder_names"])
    named_row = _loan_row(APIClient().get(url))

    makerspace.public_stats_show_holder_names = False
    makerspace.save(update_fields=["public_stats_show_holder_names"])
    private_row = _loan_row(APIClient().get(url))

    assert set(private_row) == {"item_name", "holder_name", "due", "since"}
    assert private_row["item_name"] == named_row["item_name"] == "Thermal Camera"
    assert private_row["due"] == named_row["due"]
    assert private_row["since"] == named_row["since"]


def test_disabled_holder_names_do_not_resolve_public_display_name(current_loan, monkeypatch):
    _makerspace, url = current_loan
    calls = 0

    def display_name_spy(**kwargs):
        nonlocal calls
        calls += 1
        return "Unexpected"

    monkeypatch.setattr(
        "apps.inventory.public_stats_hardware.public_display_name",
        display_name_spy,
    )

    row = _loan_row(APIClient().get(url))

    assert row["holder_name"] == "Member"
    assert calls == 0


def test_space_manager_can_patch_holder_names_but_inventory_manager_cannot():
    makerspace = Makerspace.objects.create(
        name="Holder settings lab",
        slug="holder-settings-lab",
    )
    manager = User.objects.create_user(username="holder-settings-manager")
    inventory_manager = User.objects.create_user(username="holder-settings-inventory")
    MakerspaceMembership.objects.create(
        makerspace=makerspace,
        user=manager,
        role=MakerspaceMembership.Role.SPACE_MANAGER,
    )
    MakerspaceMembership.objects.create(
        makerspace=makerspace,
        user=inventory_manager,
        role=MakerspaceMembership.Role.INVENTORY_MANAGER,
    )
    url = f"/api/v1/admin/makerspaces/{makerspace.id}"
    manager_client = APIClient()
    manager_client.force_authenticate(manager)
    inventory_client = APIClient()
    inventory_client.force_authenticate(inventory_manager)

    enabled = manager_client.patch(
        url,
        {"public_stats_show_holder_names": True},
        format="json",
    )
    disabled = manager_client.patch(
        url,
        {"public_stats_show_holder_names": False},
        format="json",
    )
    denied = inventory_client.patch(
        url,
        {"public_stats_show_holder_names": True},
        format="json",
    )

    assert enabled.status_code == 200
    assert enabled.data["public_stats_show_holder_names"] is True
    assert disabled.status_code == 200
    assert disabled.data["public_stats_show_holder_names"] is False
    assert denied.status_code == 404
    makerspace.refresh_from_db()
    assert makerspace.public_stats_show_holder_names is False
