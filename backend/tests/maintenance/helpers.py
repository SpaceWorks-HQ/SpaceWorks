from apps.accounts.models import User
from apps.machines.models import Machine, MachineOperator, MachineType
from apps.makerspaces.models import MakerspaceMembership
from tests.return_helpers import make_member, make_space
from tests.handout_roles import make_handout_member


def make_machine_setup(slug, *, operator_level=None):
    makerspace = make_space(slug)
    modules = set(makerspace.enabled_modules or [])
    modules.update({"machines", "maintenance"})
    makerspace.enabled_modules = sorted(modules)
    makerspace.save(update_fields=["enabled_modules"])
    manager = make_member(f"{slug}-manager", makerspace)
    machine_type = MachineType.objects.create(
        makerspace=makerspace,
        slug=f"{slug}-type",
        name="Maintenance Test Type",
    )
    machine = Machine.objects.create(
        makerspace=makerspace,
        machine_type=machine_type,
        name="Test Machine",
        created_by=manager,
    )
    operator = None
    if operator_level:
        operator = make_handout_member(f"{slug}-operator", makerspace)
        MachineOperator.objects.create(
            machine=machine,
            user=operator,
            access_level=operator_level,
        )
    return makerspace, manager, machine, operator
