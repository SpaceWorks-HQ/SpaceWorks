"""Small fixtures shared only by Lane D D8 acceptance tests."""

from apps.accounts.models import User
from apps.machines.models import Machine, MachineType
from apps.makerspaces.models import Makerspace, MakerspaceMembership, MakerspaceRole


def isolated_machine_actor(slug, *, stub=False):
    """Create a live member with no role or type-manager machine authority."""
    space = Makerspace.objects.create(
        name=slug,
        slug=slug,
        enabled_modules=["machines", "notifications"],
    )
    role = MakerspaceRole.objects.create(
        makerspace=space,
        name="D8 inert member",
        slug="d8-inert-member",
        granted_actions=[],
    )
    actor = User.objects.create_user(
        username=f"{slug}-actor",
        email=f"{slug}-actor@example.test",
        access_status=User.AccessStatus.ACTIVE,
        is_tenant_dump_stub=stub,
    )
    MakerspaceMembership.objects.create(
        makerspace=space,
        user=actor,
        role=MakerspaceMembership.Role.CUSTOM,
        assigned_role=role,
        status="active",
    )
    machine_type = MachineType.objects.create(
        makerspace=space,
        slug="d8-machine-type",
        name="D8 machine type",
        managing_action="",
    )
    machine = Machine.objects.create(
        makerspace=space,
        machine_type=machine_type,
        name="D8 isolated machine",
    )
    return space, actor, machine
