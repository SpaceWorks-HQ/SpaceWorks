import pytest

from apps.machines.access import (
    can_delegate_operators,
    can_manage_machine,
    can_operate_machine,
    can_retire_machine,
    can_unretire_machine,
    operator_level,
)
from apps.machines.models import MachineOperator
from tests.tenant_migration.d8_test_helpers import isolated_machine_actor


pytestmark = pytest.mark.django_db


EXPECTED_CAPABILITIES = {
    MachineOperator.AccessLevel.OPERATE: (True, False, False, False, False),
    MachineOperator.AccessLevel.MANAGE: (True, True, False, False, False),
    MachineOperator.AccessLevel.FULL: (True, True, True, True, False),
}


def _capabilities(actor, machine):
    return (
        can_operate_machine(actor, machine),
        can_manage_machine(actor, machine),
        can_delegate_operators(actor, machine),
        can_retire_machine(actor, machine),
        can_unretire_machine(actor, machine),
    )


@pytest.mark.parametrize("level", tuple(EXPECTED_CAPABILITIES))
def test_activated_operator_grant_confers_only_its_specified_authority(level):
    _space, actor, machine = isolated_machine_actor(f"d8-operator-{level}")
    MachineOperator.objects.create(machine=machine, user=actor, access_level=level)

    assert operator_level(actor, machine) == level
    assert _capabilities(actor, machine) == EXPECTED_CAPABILITIES[level]


@pytest.mark.parametrize("level", tuple(EXPECTED_CAPABILITIES))
@pytest.mark.xfail(strict=True, reason="SPEC BUG SECURITY: backend/apps/machines/access.py:36-46 is_active_member omits the is_tenant_dump_stub denial, so inert stub users receive machine-operator authority.")
def test_referential_stub_operator_grant_is_inert_for_every_access_level(level):
    _space, actor, machine = isolated_machine_actor(
        f"d8-stub-operator-{level}", stub=True
    )
    MachineOperator.objects.create(machine=machine, user=actor, access_level=level)

    assert operator_level(actor, machine) is None
    assert _capabilities(actor, machine) == (False, False, False, False, False)
