import pytest
from django.db import IntegrityError, transaction

from apps.machines.consumable_scope import pool_serves_machine, pools_for_machine_q
from apps.machines.models import Machine, MachineConsumablePool, MachineType
from tests.return_helpers import make_space


pytestmark = pytest.mark.django_db


def test_python_and_queryset_scopes_agree_for_machine_type_and_space_wide_pools():
    space = make_space("consumable-scope")
    machine_type = MachineType.objects.create(
        makerspace=space, slug="scope-type", name="Scope type"
    )
    machine = Machine.objects.create(
        makerspace=space, machine_type=machine_type, name="Scoped machine"
    )
    pools = [
        MachineConsumablePool.objects.create(
            makerspace=space,
            machine=machine,
            material="Machine stock",
            initial_grams="100",
            remaining_grams="100",
        ),
        MachineConsumablePool.objects.create(
            makerspace=space,
            machine_type=machine_type,
            material="Type stock",
            initial_grams="100",
            remaining_grams="100",
        ),
        MachineConsumablePool.objects.create(
            makerspace=space,
            material="Shared stock",
            initial_grams="100",
            remaining_grams="100",
        ),
    ]

    matched_ids = set(
        MachineConsumablePool.objects.filter(pools_for_machine_q(machine)).values_list(
            "id", flat=True
        )
    )

    assert matched_ids == {pool.pk for pool in pools}
    assert all(pool_serves_machine(pool, machine) for pool in pools)


def test_python_and_queryset_scopes_reject_another_makerspaces_shared_pool():
    space = make_space("consumable-scope-own")
    other_space = make_space("consumable-scope-other")
    machine_type = MachineType.objects.create(
        makerspace=space, slug="own-type", name="Own type"
    )
    machine = Machine.objects.create(
        makerspace=space, machine_type=machine_type, name="Own machine"
    )
    foreign_pool = MachineConsumablePool.objects.create(
        makerspace=other_space,
        material="Foreign shared stock",
        initial_grams="100",
        remaining_grams="100",
    )

    matched_ids = set(
        MachineConsumablePool.objects.filter(pools_for_machine_q(machine)).values_list(
            "id", flat=True
        )
    )

    assert not pool_serves_machine(foreign_pool, machine)
    assert foreign_pool.pk not in matched_ids


def test_database_rejects_a_pool_with_both_machine_and_machine_type_scope():
    space = make_space("consumable-scope-constraint")
    machine_type = MachineType.objects.create(
        makerspace=space, slug="constraint-type", name="Constraint type"
    )
    machine = Machine.objects.create(
        makerspace=space, machine_type=machine_type, name="Constraint machine"
    )

    with pytest.raises(IntegrityError), transaction.atomic():
        MachineConsumablePool.objects.create(
            makerspace=space,
            machine=machine,
            machine_type=machine_type,
            material="Invalid stock",
            initial_grams="100",
            remaining_grams="100",
        )
