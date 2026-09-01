"""B7a public printer metrics read only the authoritative machine kernel."""

import json
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.inventory.public_stats import build_public_stats
from apps.machines.models import (
    Machine, MachineConsumableAdjustment, MachineConsumablePool, MachineServiceRequest,
    MachineType, MachineUsageEntry, ServiceQueue,
)
from tests.return_helpers import make_space, make_user


pytestmark = pytest.mark.django_db


def test_printer_stats_require_printing_and_machine_service_modules():
    makerspace = make_space("b7a-printing-disabled")
    makerspace.enabled_modules = ["machine_service"]
    makerspace.save(update_fields=["enabled_modules"])

    assert build_public_stats(makerspace)["printing"] is None


def _request(*, makerspace, queue, requester, status, title, machine=None, pool=None, minutes=0, grams="0", completed_at=None):
    return MachineServiceRequest.objects.create(
        makerspace=makerspace, queue=queue, requester=requester, assigned_machine=machine,
        run_consumable_pool=pool, status=status, title=title, requester_name="Private Person",
        contact_email="private@example.test", contact_phone="555-0100", actual_minutes=minutes,
        actual_consumed_grams=Decimal(grams), completed_at=completed_at,
    )


def test_flipped_public_printer_stats_project_kernel_metrics_without_pii():
    makerspace = make_space("b7a-public-stats")
    requester = make_user("b7a-public-stats-requester")
    printer_type = MachineType.objects.get(makerspace__isnull=True, slug="3d_printer")
    printer = Machine.objects.create(
        makerspace=makerspace, machine_type=printer_type, name="Kernel MK4", type_payload={"model": "MK4"},
    )
    queue = ServiceQueue.objects.create(makerspace=makerspace, machine_type=printer_type, name="Public print queue")
    pool = MachineConsumablePool.objects.create(
        makerspace=makerspace, machine=printer, material="PLA", color="Blue", brand="MakerFil",
        initial_grams=Decimal("100.00"), remaining_grams=Decimal("80.00"),
    )
    completed = _request(
        makerspace=makerspace, queue=queue, requester=requester, status=MachineServiceRequest.Status.COMPLETED,
        title="Private completed job", machine=printer, pool=pool, minutes=60, grams="12.50", completed_at=timezone.now(),
    )
    _request(makerspace=makerspace, queue=queue, requester=requester, status=MachineServiceRequest.Status.PENDING, title="Private pending job")
    _request(makerspace=makerspace, queue=queue, requester=requester, status=MachineServiceRequest.Status.ACCEPTED, title="Private accepted job")
    _request(makerspace=makerspace, queue=queue, requester=requester, status=MachineServiceRequest.Status.IN_PROGRESS, title="Private active job", machine=printer)
    usage = MachineUsageEntry.objects.create(
        machine=printer, source=MachineUsageEntry.Source.TYPED_MANUAL, hours=Decimal("1.25"),
        consumable_pool=pool, consumed_grams=Decimal("7.00"), title="Private manual job",
        requester_name="Private Person", contact_email="private@example.test", contact_phone="555-0100",
    )
    MachineConsumableAdjustment.objects.create(
        makerspace=makerspace, consumable_pool=pool, kind=MachineConsumableAdjustment.Kind.MANUAL,
        quantity_delta=Decimal("-7.00"), usage_entry=usage,
    )

    stats = build_public_stats(makerspace)["printing"]

    assert stats["filament_trend"] == [{"period": timezone.localtime(completed.completed_at).strftime("%Y-%m"), "grams": 12.5}]
    assert stats["by_brand"] == [{"brand": "MakerFil", "grams": 12.5}]
    assert stats["per_printer"] == [{"name": "Kernel MK4", "model": "", "jobs": 1, "hours": 2.25, "grams": 19.5, "image_url": None}]
    assert stats["jobs"] == {
        "completed": 1,
        "status_counts": {"pending": 1, "accepted": 1, "printing": 1, "completed": 1, "collected": 0, "failed": 0, "rejected": 0},
        "queue": {"pending": 1, "accepted": 1, "printing": 1},
    }
    public_payload = json.dumps(stats)
    for private_value in ("Private Person", "private@example.test", "555-0100", "Private completed job", "Private manual job"):
        assert private_value not in public_payload
