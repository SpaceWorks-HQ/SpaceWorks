import pytest
from django.core.exceptions import ValidationError

from apps.machines.models import MachineType
from apps.machines.printer_capabilities import PRINTER_CONFIG, PRINTER_SLUG


def _custom_type(config):
    return MachineType(
        makerspace_id=1,
        slug="laser-cutter",
        name="Laser cutter",
        capability_config=config,
    )


def test_custom_type_accepts_material_and_colour_presets():
    machine_type = _custom_type(
        {
            "metering_unit": "count",
            "requires_booking": True,
            "accepted_materials": ["Plywood", "Acrylic"],
            "accepted_colours": ["Clear", "Black"],
        }
    )

    machine_type.clean()


@pytest.mark.parametrize("key", ["accepted_materials", "accepted_colours"])
def test_custom_type_rejects_blank_preset_entry(key):
    machine_type = _custom_type(
        {"metering_unit": "count", "requires_booking": False, key: ["Valid", " "]}
    )

    with pytest.raises(ValidationError, match=f"Machine type {key} must be a non-empty list of names"):
        machine_type.clean()


@pytest.mark.parametrize("key", ["accepted_materials", "accepted_colours"])
def test_custom_type_rejects_empty_preset_list(key):
    machine_type = _custom_type(
        {"metering_unit": "count", "requires_booking": False, key: []}
    )

    with pytest.raises(ValidationError, match=f"Machine type {key} must be a non-empty list of names"):
        machine_type.clean()


@pytest.mark.parametrize("key", ["accepted_materials", "accepted_colours"])
def test_custom_type_rejects_case_insensitive_duplicate(key):
    machine_type = _custom_type(
        {"metering_unit": "count", "requires_booking": False, key: ["Plywood", "PLYWOOD"]}
    )

    with pytest.raises(ValidationError, match=f"Machine type {key} cannot contain duplicates"):
        machine_type.clean()


def test_builtin_printer_contract_is_unaffected():
    printer = MachineType(
        makerspace=None,
        slug=PRINTER_SLUG,
        name="3D printer",
        is_builtin=True,
        capability_config=PRINTER_CONFIG,
    )

    printer.clean()
