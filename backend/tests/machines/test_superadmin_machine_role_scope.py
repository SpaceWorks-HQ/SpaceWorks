"""Regression coverage for superadmins reduced to a hidden-space membership role."""

import pytest

from apps.accounts import rbac
from apps.accounts.models import User
from apps.admin_api.views_machine_service_files import _narrow_files_to_machine_scope
from apps.admin_api.views_machine_service_printer import scoped_pools
from apps.machines import access
from apps.machines.models import (
    Machine,
    MachineConsumablePool,
    MachineType,
    RoleMachineTypeScope,
    ServiceRequestFile,
)
from apps.makerspaces.models import Makerspace, MakerspaceMembership, MakerspaceRole

pytestmark = pytest.mark.django_db


def _machine(space, slug):
    machine_type = MachineType.objects.create(
        makerspace=space,
        slug=f"{space.slug}-{slug}",
        name=slug.title(),
    )
    return Machine.objects.create(
        makerspace=space,
        machine_type=machine_type,
        name=slug.title(),
    )


def _superadmin(username):
    return User.objects.create_user(
        username=username,
        email=f"{username}@example.test",
        role=User.Role.SUPERADMIN,
        access_status=User.AccessStatus.ACTIVE,
        is_staff=True,
        is_superuser=True,
    )


def _file(machine, owner, suffix):
    return ServiceRequestFile.objects.create(
        makerspace=machine.makerspace,
        machine=machine,
        kind=ServiceRequestFile.Kind.ATTACHMENT,
        object_key=f"machine-scope/{suffix}",
        owner_user_id=owner.pk,
    )


def _pool(machine, suffix):
    return MachineConsumablePool.objects.create(
        makerspace=machine.makerspace,
        machine=machine,
        material=suffix,
        initial_grams="100.00",
        remaining_grams="100.00",
    )


@pytest.fixture
def scoped_superadmin_lab():
    hidden = Makerspace.objects.create(
        name="Hidden scoped lab", slug="hidden-scoped-lab"
    )
    hidden.superadmin_access_enabled = False
    hidden.save(update_fields=["superadmin_access_enabled"])
    linked = _machine(hidden, "linked-laser")
    unlinked = _machine(hidden, "unlinked-printer")

    visible = Makerspace.objects.create(
        name="Visible global lab", slug="visible-global-lab"
    )
    global_one = _machine(visible, "global-laser")
    global_two = _machine(visible, "global-printer")

    scoped = _superadmin("hidden-scoped-superadmin")
    role = MakerspaceRole.objects.create(
        makerspace=hidden,
        name="Hidden laser team",
        slug="hidden-laser-team",
        granted_actions=[rbac.Action.MANAGE_MACHINES],
    )
    RoleMachineTypeScope.objects.create(
        role=role, machine_type=linked.machine_type
    )
    MakerspaceMembership.objects.create(
        user=scoped,
        makerspace=hidden,
        role=MakerspaceMembership.Role.CUSTOM,
        assigned_role=role,
    )
    ordinary = _superadmin("ordinary-global-superadmin")

    machines = (linked, unlinked, global_one, global_two)
    files = tuple(
        _file(machine, scoped, f"file-{index}")
        for index, machine in enumerate(machines)
    )
    pools = tuple(
        _pool(machine, f"pool-{index}")
        for index, machine in enumerate(machines)
    )
    return {
        "hidden": hidden,
        "visible": visible,
        "linked": linked,
        "unlinked": unlinked,
        "global_machines": (global_one, global_two),
        "scoped": scoped,
        "ordinary": ordinary,
        "files": files,
        "pools": pools,
    }


def test_hidden_space_superadmin_machine_queryset_honors_role_links(
    scoped_superadmin_lab,
):
    lab = scoped_superadmin_lab

    # This is the dangerous disagreement: action scope is globally ALL, while the
    # explicit hidden-space membership must still narrow that makerspace by role links.
    assert (
        rbac.makerspaces_for_action(lab["scoped"], rbac.Action.MANAGE_MACHINES)
        is rbac.ALL
    )

    machine_ids = set(
        access.scope_machines_for_actor(lab["scoped"], Machine.objects.all())
        .values_list("pk", flat=True)
    )
    manageable_ids = set(
        access.scope_manageable_machines_for_actor(
            lab["scoped"], Machine.objects.all()
        ).values_list("pk", flat=True)
    )
    expected_ids = {lab["linked"].pk} | {
        machine.pk for machine in lab["global_machines"]
    }

    assert machine_ids == expected_ids
    assert manageable_ids == expected_ids
    assert lab["unlinked"].pk not in machine_ids


def test_hidden_space_superadmin_service_files_honor_role_links(
    scoped_superadmin_lab,
):
    lab = scoped_superadmin_lab

    file_ids = set(
        _narrow_files_to_machine_scope(
            lab["scoped"], ServiceRequestFile.objects.all()
        ).values_list("pk", flat=True)
    )

    assert file_ids == {
        lab["files"][0].pk,
        lab["files"][2].pk,
        lab["files"][3].pk,
    }
    assert lab["files"][1].pk not in file_ids


def test_hidden_space_superadmin_consumable_pools_honor_role_links(
    scoped_superadmin_lab,
):
    lab = scoped_superadmin_lab

    pool_ids = set(
        scoped_pools(lab["scoped"], MachineConsumablePool.objects.all())
        .values_list("pk", flat=True)
    )

    assert pool_ids == {
        lab["pools"][0].pk,
        lab["pools"][2].pk,
        lab["pools"][3].pk,
    }
    assert lab["pools"][1].pk not in pool_ids


def test_ordinary_superadmin_without_memberships_remains_unrestricted(
    scoped_superadmin_lab,
):
    lab = scoped_superadmin_lab
    ordinary = lab["ordinary"]
    lab["hidden"].superadmin_access_enabled = True
    lab["hidden"].save(update_fields=["superadmin_access_enabled"])

    assert (
        rbac.makerspaces_for_action(ordinary, rbac.Action.MANAGE_MACHINES)
        is rbac.ALL
    )

    machine_ids = set(
        access.scope_machines_for_actor(ordinary, Machine.objects.all())
        .values_list("pk", flat=True)
    )
    file_ids = set(
        _narrow_files_to_machine_scope(
            ordinary, ServiceRequestFile.objects.all()
        ).values_list("pk", flat=True)
    )
    pool_ids = set(
        scoped_pools(ordinary, MachineConsumablePool.objects.all())
        .values_list("pk", flat=True)
    )

    assert machine_ids == {machine.pk for machine in Machine.objects.all()}
    assert file_ids == {file.pk for file in lab["files"]}
    assert pool_ids == {pool.pk for pool in lab["pools"]}
