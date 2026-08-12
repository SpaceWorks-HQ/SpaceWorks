"""B7b procurement conversion is kernel-only for every makerspace."""

from decimal import Decimal

import pytest
from rest_framework.exceptions import ValidationError

from apps.machines.models import Machine, MachineConsumablePool, MachineType
from apps.procurement.models import ToBuyItem
from apps.procurement.services import move_to_printing
from tests.return_helpers import make_space, make_user


pytestmark = pytest.mark.django_db


def _received_item(makerspace, name):
    return ToBuyItem.objects.create(
        makerspace=makerspace, kind=ToBuyItem.Kind.PRINTING, name=name, status=ToBuyItem.Status.RECEIVED,
    )


def test_procurement_move_always_uses_kernel_and_records_kernel_destinations():
    makerspace = make_space("b7a-procurement-kernel")
    actor = make_user("b7a-procurement-kernel-actor")
    printer = move_to_printing(
        actor, _received_item(makerspace, "Printer"), target="printer",
        data={"name": "Kernel MK4", "model": "MK4", "status": "active"},
    )
    pool = move_to_printing(
        actor, _received_item(makerspace, "PLA spool"), target="spool",
        data={"printer": printer.id, "material": "PLA", "color": "Blue", "brand": "MakerFil",
              "initial_weight_grams": "1000.00", "remaining_weight_grams": "900.00"},
    )
    pool.refresh_from_db()
    assert isinstance(printer, Machine)
    assert (printer.machine_type.slug, printer.type_payload) == ("3d_printer", {"model": "MK4"})
    assert isinstance(pool, MachineConsumablePool)
    assert (pool.machine, pool.initial_grams, pool.remaining_grams) == (printer, Decimal("1000.00"), Decimal("900.00"))

    printer_item = ToBuyItem.objects.get(name="Printer")
    pool_item = ToBuyItem.objects.get(name="PLA spool")
    assert printer_item.resulting_machine == printer
    assert pool_item.resulting_pool == pool

    other_space = make_space("b7b-procurement-kernel")
    other_printer = move_to_printing(
        make_user("b7b-procurement-kernel-actor"), _received_item(other_space, "Other Printer"),
        target="printer", data={"name": "Other MK4", "model": "MK4"},
    )
    assert isinstance(other_printer, Machine)
    assert not MachineConsumablePool.objects.filter(makerspace=other_space).exists()

def test_kernel_procurement_move_validates_pool_material_and_weights():
    makerspace = make_space("b7a-procurement-kernel-validation")
    actor = make_user("b7a-procurement-kernel-validation-actor")

    with pytest.raises(ValidationError) as blank_material:
        move_to_printing(
            actor, _received_item(makerspace, "Blank material"), target="spool",
            data={"material": "  ", "initial_weight_grams": "100"},
        )
    assert blank_material.value.detail == {"material": "This field is required."}

    with pytest.raises(ValidationError) as negative_initial:
        move_to_printing(
            actor, _received_item(makerspace, "Negative initial"), target="spool",
            data={"material": "PLA", "initial_weight_grams": "-1"},
        )
    assert negative_initial.value.detail == {
        "initial_weight_grams": "Must be zero or greater.",
    }


def test_typed_procurement_cannot_create_another_machine_type():
    makerspace = make_space("b7a-procurement-type-safety")
    actor = make_user("b7a-procurement-type-safety-actor")
    laser_type = MachineType.objects.create(
        makerspace=makerspace, slug="procured-laser", name="Procured laser"
    )
    item = _received_item(makerspace, "Typed laser")
    item.machine_type = laser_type
    item.save(update_fields=["machine_type"])

    with pytest.raises(ValidationError) as mismatch:
        move_to_printing(
            actor,
            item,
            target="printer",
            data={"name": "Wrong type", "model": "MK4"},
        )

    item.refresh_from_db()
    assert "machine_type" in mismatch.value.detail
    assert item.moved_to_inventory_at is None
    assert item.resulting_machine_id is None
    assert not Machine.objects.filter(makerspace=makerspace, name="Wrong type").exists()

    printer_type = MachineType.objects.create(
        makerspace=makerspace, slug="3d_printer", name="Local printer"
    )
    printer = Machine.objects.create(
        makerspace=makerspace, machine_type=printer_type, name="Other type printer"
    )
    pool_item = _received_item(makerspace, "Typed coolant")
    pool_item.machine_type = laser_type
    pool_item.save(update_fields=["machine_type"])

    with pytest.raises(ValidationError) as pool_mismatch:
        move_to_printing(
            actor,
            pool_item,
            target="spool",
            data={
                "printer": printer.pk,
                "material": "PLA",
                "initial_weight_grams": "100.00",
            },
        )

    pool_item.refresh_from_db()
    assert "machine_type" in pool_mismatch.value.detail
    assert pool_item.moved_to_inventory_at is None
    assert pool_item.resulting_pool_id is None
    assert not MachineConsumablePool.objects.filter(machine=printer).exists()
