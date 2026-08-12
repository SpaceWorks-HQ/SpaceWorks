"""C.1 generic machine metering behavior."""

from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from rest_framework.exceptions import ValidationError as DRFValidationError

from apps.machines import role_scope
from apps.machines.metering import MeteringUnit, validate_type_config
from apps.machines.models import Machine, MachineServiceRequest, MachineType
from apps.machines.service_consumable_pools import create_pool, reconcile_request, reserve_for_request
from apps.machines.service_workflow import accept, complete, fail, start, submit
from tests.return_helpers import make_space, make_user


pytestmark = pytest.mark.django_db


def _machine(space, config):
    kind = MachineType.objects.create(
        makerspace=space, slug=f"meter-{space.id}", name="Metered", capability_config=config
    )
    return Machine.objects.create(makerspace=space, machine_type=kind, name="Meter")


def test_pool_defaults_to_grams_and_retains_quantities_for_milliliters():
    space, actor = make_space("meter-pools"), make_user("meter-pool-actor")
    grams = create_pool(space, actor, material="PLA", initial_grams="20")
    milliliters = create_pool(space, actor, material="Resin", initial_grams="20", unit="milliliters")
    assert (grams.unit, grams.remaining_grams, grams.low_threshold_grams) == ("grams", Decimal("20.00"), None)
    assert (milliliters.unit, milliliters.initial_grams, milliliters.remaining_grams) == ("milliliters", Decimal("20.00"), Decimal("20.00"))


def test_generic_type_config_validation_and_protected_printer_contract():
    validate_type_config({"metering_unit": "minutes", "requires_booking": False}, is_custom=True)
    for config in (
        {"metering_unit": "flat"}, {"rate_per_unit": "1"}, {"flat_fee": "1"},
        {"currency": "USD"}, {"payment_enabled": True}, {"requires_booking": "false"},
    ):
        with pytest.raises(ValidationError):
            validate_type_config(config)

    printer = MachineType.objects.get(makerspace__isnull=True, slug="3d_printer")
    printer.full_clean()


def test_non_grams_request_reserves_and_reconciles_in_its_metering_unit():
    space, actor, requester = make_space("meter-volume"), make_user("meter-volume-actor"), make_user("meter-volume-requester")
    machine = _machine(space, {"metering_unit": MeteringUnit.VOLUME})
    request = submit(machine, requester, actor=actor, requester_name="R", contact_email="r@test", contact_phone="1", title="Resin job")
    pool = create_pool(space, actor, material="Resin", initial_grams="100", machine=machine, unit="milliliters")

    reserve_for_request(request, actor, pool=pool, planned_quantity="20", machine=machine)
    reconcile_request(request, actor, actual_quantity="12")
    request.refresh_from_db()
    pool.refresh_from_db()

    assert (request.metering_unit, request.planned_quantity, request.reserved_quantity, request.actual_consumed_quantity) == ("volume", Decimal("20.00"), Decimal("0.00"), Decimal("12.00"))
    assert (request.planned_grams, request.actual_consumed_grams, pool.remaining_grams) == (Decimal("0.00"), Decimal("0.00"), Decimal("88.00"))
    assert list(pool.adjustments.values_list("metering_unit", "consumed_quantity")) == [("volume", Decimal("-20.00")), ("volume", Decimal("8.00"))]


def test_grams_reservation_keeps_legacy_and_generic_quantities_in_sync():
    space, actor, requester = make_space("meter-grams"), make_user("meter-grams-actor"), make_user("meter-grams-requester")
    machine = _machine(space, {})
    request = submit(machine, requester, actor=actor, requester_name="R", contact_email="r@test", contact_phone="1", title="Filament job")
    pool = create_pool(space, actor, material="PLA", initial_grams="50", machine=machine)
    reserve_for_request(request, actor, pool=pool, planned_grams="10", machine=machine)
    reconcile_request(request, actor, actual_grams="8")
    request.refresh_from_db()
    assert (request.metering_unit, request.planned_grams, request.planned_quantity, request.actual_consumed_grams, request.actual_consumed_quantity) == ("weight", Decimal("10.00"), Decimal("10.00"), Decimal("8.00"), Decimal("8.00"))


@pytest.mark.parametrize("terminal", ["complete", "fail"])
def test_workflow_reconciles_generic_reservations_in_quantity_space(terminal):
    space, actor, requester = make_space(f"meter-workflow-{terminal}"), make_user(f"meter-workflow-{terminal}-actor"), make_user(f"meter-workflow-{terminal}-requester")
    machine = _machine(space, {"metering_unit": MeteringUnit.VOLUME})
    request = submit(machine, requester, actor=actor, requester_name="R", contact_email="r@test", contact_phone="1", title="Resin job")
    pool = create_pool(space, actor, material="Resin", initial_grams="100", machine=machine, unit="milliliters")

    reserve_for_request(request, actor, pool=pool, planned_quantity="20", machine=machine)
    accept(request, actor)
    start(request, actor, role_scope.EXEMPT, machine_id=machine.pk)
    if terminal == "complete":
        complete(request, actor, actual_minutes=1, consumptions=[])
    else:
        fail(request, actor, reason="Failed run", percent_complete=50, actual_minutes=1, consumptions=[])

    request.refresh_from_db()
    pool.refresh_from_db()
    expected_actual = Decimal("20.00") if terminal == "complete" else Decimal("10.00")
    assert (request.metering_unit, request.reserved_quantity, request.actual_consumed_quantity) == ("volume", Decimal("0.00"), expected_actual)
    assert (request.planned_grams, request.reserved_grams, request.actual_consumed_grams) == (Decimal("0.00"), Decimal("0.00"), Decimal("0.00"))
    assert pool.remaining_grams == Decimal("100.00") - expected_actual


def test_generic_printer_reservation_enforces_legacy_pool_compatibility():
    space, actor, requester = make_space("meter-printer"), make_user("meter-printer-actor"), make_user("meter-printer-requester")
    printer_type = MachineType.objects.get(makerspace__isnull=True, slug="3d_printer")
    machine = Machine.objects.create(makerspace=space, machine_type=printer_type, name="Printer")
    materials = printer_type.capability_config["accepted_materials"]
    colors = printer_type.capability_config["accepted_colours"]
    material, color = materials[0], colors[0]
    alternate_material = next((item for item in materials if item.casefold() != material.casefold()), None)
    alternate_color = next((item for item in colors if item.casefold() != color.casefold()), None)
    assert alternate_material or alternate_color
    incompatible_material = alternate_material or material
    incompatible_color = color if alternate_material else alternate_color
    payload = {"requested_material": material, "requested_color": color, "quantity": 1}
    generic_request = submit(machine, requester, actor=actor, requester_name="R", contact_email="r@test", contact_phone="1", title="Print", capability_payload=payload)
    legacy_request = submit(machine, requester, actor=actor, requester_name="R", contact_email="r@test", contact_phone="1", title="Print", capability_payload=payload)
    incompatible = create_pool(space, actor, material=incompatible_material, color=incompatible_color, initial_grams="50", machine=machine)
    compatible = create_pool(space, actor, material=material, color=color, initial_grams="50", machine=machine)

    with pytest.raises(DRFValidationError) as legacy_error:
        reserve_for_request(legacy_request, actor, pool=incompatible, planned_grams="10", machine=machine)
    with pytest.raises(type(legacy_error.value)) as generic_error:
        reserve_for_request(generic_request, actor, pool=incompatible, planned_quantity="10", machine=machine)
    assert generic_error.value.detail == legacy_error.value.detail

    reserve_for_request(generic_request, actor, pool=compatible, planned_quantity="10", machine=machine)
    generic_request.refresh_from_db()
    assert (generic_request.run_consumable_pool_id, generic_request.reserved_quantity) == (compatible.pk, Decimal("10.00"))

def test_staff_workflow_reconciles_generic_partial_failure_and_explicit_completion():
    space, actor, requester = make_space("meter-staff-workflow"), make_user("meter-staff-actor"), make_user("meter-staff-requester")
    machine = _machine(space, {"metering_unit": MeteringUnit.VOLUME})
    pool = create_pool(space, actor, material="Resin", initial_grams="100", machine=machine, unit="milliliters")

    failed = submit(machine, requester, actor=actor, requester_name="R", contact_email="r@test", contact_phone="1", title="Partial resin job")
    accept(failed, actor)
    start(failed, actor, role_scope.EXEMPT, machine_id=machine.pk, consumable_pool_id=pool.pk, planned_quantity="100")
    pool.refresh_from_db()
    assert pool.remaining_grams == Decimal("0.00")
    fail(failed, actor, reason="Stopped halfway", percent_complete=50, actual_minutes=1, consumptions=[])
    failed.refresh_from_db()
    pool.refresh_from_db()
    assert (failed.actual_consumed_quantity, pool.remaining_grams) == (Decimal("50.00"), Decimal("50.00"))

    completed = submit(machine, requester, actor=actor, requester_name="R", contact_email="r@test", contact_phone="1", title="Measured resin job")
    accept(completed, actor)
    start(completed, actor, role_scope.EXEMPT, machine_id=machine.pk, consumable_pool_id=pool.pk, planned_quantity="20")
    complete(completed, actor, actual_minutes=1, consumptions=[], actual_quantity="12")
    completed.refresh_from_db()
    pool.refresh_from_db()
    assert (completed.actual_consumed_quantity, pool.remaining_grams) == (Decimal("12.00"), Decimal("38.00"))
