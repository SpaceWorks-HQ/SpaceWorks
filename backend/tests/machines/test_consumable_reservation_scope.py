from decimal import Decimal

import pytest
from rest_framework.exceptions import ValidationError

from apps.machines.metering import MeteringUnit
from apps.machines.models import Machine, MachineType
from apps.machines.service_consumable_pools import create_pool, reserve_for_request
from apps.machines.service_workflow import submit
from apps.procurement.models import ToBuyItem
from tests.return_helpers import make_space, make_user


pytestmark = pytest.mark.django_db


def _type(space, slug, *, metering_unit=MeteringUnit.WEIGHT):
    return MachineType.objects.create(
        makerspace=space,
        slug=slug,
        name=slug.replace("-", " ").title(),
        capability_config={
            "metering_unit": metering_unit,
            "requires_booking": False,
        },
    )


def _request(machine, requester, actor, title):
    return submit(
        machine,
        requester,
        actor=actor,
        requester_name="Requester",
        contact_email=requester.email,
        contact_phone="1",
        title=title,
    )


def test_grams_reservation_accepts_the_machine_type_pool_and_rejects_another_type():
    space = make_space("reservation-grams-type-scope")
    actor = make_user("reservation-grams-actor")
    requester = make_user("reservation-grams-requester")
    machine_type = _type(space, "reservation-grams-a")
    other_type = _type(space, "reservation-grams-b")
    machine = Machine.objects.create(
        makerspace=space, machine_type=machine_type, name="Gram machine"
    )
    compatible = create_pool(
        space,
        actor,
        material="Compatible grams",
        initial_grams="100",
        machine_type=machine_type,
    )
    incompatible = create_pool(
        space,
        actor,
        material="Other grams",
        initial_grams="100",
        machine_type=other_type,
    )

    with pytest.raises(ValidationError) as rejected:
        reserve_for_request(
            _request(machine, requester, actor, "Rejected grams"),
            actor,
            pool=incompatible,
            planned_grams="20",
            machine=machine,
        )
    accepted = _request(machine, requester, actor, "Accepted grams")
    reserve_for_request(
        accepted,
        actor,
        pool=compatible,
        planned_grams="20",
        machine=machine,
    )

    accepted.refresh_from_db()
    compatible.refresh_from_db()
    assert "consumable_pool" in rejected.value.detail
    assert accepted.run_consumable_pool_id == compatible.pk
    assert accepted.reserved_grams == Decimal("20.00")
    assert compatible.remaining_grams == Decimal("80.00")


def test_generic_quantity_reservation_applies_the_same_type_scope_rule():
    space = make_space("reservation-volume-type-scope")
    actor = make_user("reservation-volume-actor")
    requester = make_user("reservation-volume-requester")
    machine_type = _type(
        space, "reservation-volume-a", metering_unit=MeteringUnit.VOLUME
    )
    other_type = _type(
        space, "reservation-volume-b", metering_unit=MeteringUnit.VOLUME
    )
    machine = Machine.objects.create(
        makerspace=space, machine_type=machine_type, name="Volume machine"
    )
    compatible = create_pool(
        space,
        actor,
        material="Compatible liquid",
        quantity="100",
        unit="milliliters",
        machine_type=machine_type,
    )
    incompatible = create_pool(
        space,
        actor,
        material="Other liquid",
        quantity="100",
        unit="milliliters",
        machine_type=other_type,
    )

    with pytest.raises(ValidationError) as rejected:
        reserve_for_request(
            _request(machine, requester, actor, "Rejected volume"),
            actor,
            pool=incompatible,
            planned_quantity="20",
            machine=machine,
        )
    accepted = _request(machine, requester, actor, "Accepted volume")
    reserve_for_request(
        accepted,
        actor,
        pool=compatible,
        planned_quantity="20",
        machine=machine,
    )

    accepted.refresh_from_db()
    compatible.refresh_from_db()
    assert "consumable_pool" in rejected.value.detail
    assert accepted.run_consumable_pool_id == compatible.pk
    assert accepted.metering_unit == MeteringUnit.VOLUME
    assert accepted.reserved_quantity == Decimal("20.00")
    assert compatible.remaining_grams == Decimal("80.00")


def test_low_stock_from_a_type_scoped_pool_carries_the_machine_type():
    space = make_space("reservation-low-stock-type-scope")
    actor = make_user("reservation-low-stock-actor")
    requester = make_user("reservation-low-stock-requester")
    machine_type = _type(space, "reservation-low-stock-type")
    machine = Machine.objects.create(
        makerspace=space, machine_type=machine_type, name="Low-stock machine"
    )
    pool = create_pool(
        space,
        actor,
        material="Low stock",
        initial_grams="100",
        low_threshold_grams="90",
        machine_type=machine_type,
    )

    reserve_for_request(
        _request(machine, requester, actor, "Low-stock request"),
        actor,
        pool=pool,
        planned_grams="20",
        machine=machine,
    )

    item = ToBuyItem.objects.get(source_pool=pool)
    assert item.kind == ToBuyItem.Kind.PRINTING
    assert item.machine_type_id == machine_type.pk
