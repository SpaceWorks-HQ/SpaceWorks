import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.machines.models import (
    MachineConsumablePool,
    MachineServiceRequest,
    MachineType,
    ServiceQueue,
)
from apps.machines.printer_capabilities import PRINTER_CONFIG
from tests.member_submission import active_member_client
from tests.return_helpers import make_space


pytestmark = pytest.mark.django_db


def _pool(space, material, **overrides):
    values = {
        "makerspace": space,
        "material": material,
        "initial_grams": "100",
        "remaining_grams": "100",
    }
    values.update(overrides)
    return MachineConsumablePool.objects.create(**values)


def _public_pool_setup(slug):
    space = make_space(slug)
    printer_type, _ = MachineType.objects.get_or_create(
        makerspace=None,
        slug="3d_printer",
        defaults={
            "name": "3D Printer",
            "is_builtin": True,
            "capability_config": PRINTER_CONFIG,
        },
    )
    non_printer_type = MachineType.objects.create(
        makerspace=space, slug=f"{slug}-laser", name="Laser"
    )
    queue = ServiceQueue.objects.create(
        makerspace=space, machine_type=printer_type, name="Public print queue"
    )
    excluded = [
        _pool(space, "Exhausted", remaining_grams="0"),
        _pool(space, "Private", is_public=False),
        _pool(space, "Laser stock", machine_type=non_printer_type),
        _pool(space, "Liquid", unit="milliliters"),
    ]
    included = [
        _pool(space, "Shared PLA"),
        _pool(space, "Printer PETG", machine_type=printer_type),
    ]
    return space, queue, excluded, included


def test_public_pool_list_keeps_only_eligible_public_printer_gram_stock():
    space, _, excluded, included = _public_pool_setup("public-pool-list")

    response = APIClient().get(
        reverse("public-printer-service-pools", args=[space.slug])
    )

    assert response.status_code == 200
    listed_ids = {row["id"] for row in response.data}
    assert listed_ids == {pool.pk for pool in included}
    assert listed_ids.isdisjoint(pool.pk for pool in excluded)


def test_public_submit_rejects_forged_ids_for_every_ineligible_active_pool():
    space, queue, excluded, _ = _public_pool_setup("public-pool-forgery")
    _, client = active_member_client(space, "public-pool-forger")
    url = reverse("public-printer-service-request", args=[space.slug])

    for pool in excluded:
        assert pool.is_active
        response = client.post(
            url,
            {
                "queue_id": queue.pk,
                "title": f"Forged pool {pool.pk}",
                "consumable_pool_id": pool.pk,
            },
            format="json",
        )

        assert response.status_code == 400
        assert "consumable_pool_id" in response.data

    assert not MachineServiceRequest.objects.filter(makerspace=space).exists()
