"""B7a low-filament procurement automation for machine consumable pools."""

from decimal import Decimal

import pytest

from apps.audit.models import AuditLog
from apps.machines.models import Machine, MachineConsumablePool, MachineType
from apps.machines.service_consumable_pools import correct_pool, create_pool
from apps.procurement.models import ToBuyItem
from tests.return_helpers import make_space, make_user


pytestmark = pytest.mark.django_db


def test_kernel_low_stock_creates_one_open_item_and_ignores_disabled_thresholds():
    makerspace = make_space("b7a-low-stock")
    actor = make_user("b7a-low-stock-actor")
    pool = create_pool(
        makerspace, actor, material="PLA", color="Blue", initial_grams="100", low_threshold_grams="50",
    )
    correct_pool(pool, actor, quantity_delta="-50", reason="Calibration usage")
    correct_pool(pool, actor, quantity_delta="-1", reason="Another calibration")

    items = ToBuyItem.objects.filter(makerspace=makerspace, kind=ToBuyItem.Kind.PRINTING)
    assert items.count() == 1
    item = items.get()
    assert (item.name, item.status, item.created_by) == (
        "Filament restock: PLA Blue", ToBuyItem.Status.REQUESTED, actor,
    )
    assert item.machine_type_id is None
    audit = AuditLog.objects.get(action="procurement.low_stock_flagged")
    assert audit.meta == {
        "pool_id": pool.id, "remaining": "50.00", "threshold": "50.00", "to_buy_item_id": item.id,
    }

    for threshold in (None, Decimal("0.00"), Decimal("-1.00")):
        token = str(threshold).replace("-", "minus")
        disabled_space = make_space(f"b7a-low-stock-off-{token}")
        disabled_actor = make_user(f"b7a-low-stock-off-{token}-actor")
        if threshold is not None and threshold < 0:
            disabled_pool = MachineConsumablePool.objects.create(
                makerspace=disabled_space, material="PLA", initial_grams=Decimal("100.00"),
                remaining_grams=Decimal("100.00"), low_threshold_grams=threshold, created_by=disabled_actor,
            )
        else:
            disabled_pool = create_pool(
                disabled_space, disabled_actor, material="PLA", initial_grams="100", low_threshold_grams=threshold,
            )
        correct_pool(disabled_pool, disabled_actor, quantity_delta="-1", reason="Calibration usage")
        assert not ToBuyItem.objects.filter(makerspace=disabled_space, kind=ToBuyItem.Kind.PRINTING).exists()
        assert not AuditLog.objects.filter(makerspace=disabled_space, action="procurement.low_stock_flagged").exists()


def test_kernel_low_stock_flags_each_pool_with_its_own_provenance():
    # B7b keys the "at most one open restock item" contract per source pool (via the
    # source_pool FK), mirroring the legacy per-spool behavior with proper provenance:
    # two distinct low pools of the same material/color each get their own restock item,
    # while repeated debits of the SAME pool do not create a second item for it.
    makerspace = make_space("b7a-low-stock-same-name")
    actor = make_user("b7a-low-stock-same-name-actor")
    first_pool = create_pool(
        makerspace, actor, material="PLA", color="Blue", initial_grams="100", low_threshold_grams="50",
    )
    second_pool = create_pool(
        makerspace, actor, material="PLA", color="Blue", initial_grams="100", low_threshold_grams="50",
    )

    correct_pool(first_pool, actor, quantity_delta="-50", reason="Calibration usage")
    correct_pool(second_pool, actor, quantity_delta="-50", reason="Calibration usage")
    correct_pool(first_pool, actor, quantity_delta="-1", reason="More usage")  # no second item for first_pool

    items = ToBuyItem.objects.filter(
        makerspace=makerspace, kind=ToBuyItem.Kind.PRINTING, name="Filament restock: PLA Blue",
        status__in=(ToBuyItem.Status.REQUESTED, ToBuyItem.Status.APPROVED, ToBuyItem.Status.ORDERED),
    )
    assert items.count() == 2
    assert set(items.values_list("source_pool_id", flat=True)) == {first_pool.id, second_pool.id}


def test_kernel_low_stock_stamps_a_machine_bound_pools_type():
    makerspace = make_space("b7a-low-stock-machine-bound")
    actor = make_user("b7a-low-stock-machine-bound-actor")
    machine_type = MachineType.objects.create(
        makerspace=makerspace, slug="low-stock-laser", name="Low stock laser"
    )
    machine = Machine.objects.create(
        makerspace=makerspace, machine_type=machine_type, name="Laser"
    )
    pool = create_pool(
        makerspace,
        actor,
        machine=machine,
        material="Coolant",
        initial_grams="100",
        low_threshold_grams="50",
    )

    correct_pool(pool, actor, quantity_delta="-50", reason="Production use")

    item = ToBuyItem.objects.get(source_pool=pool)
    assert item.machine_type == machine_type
