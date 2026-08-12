"""Dashboard behavior for assigned roles with machine-scoped authority."""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.accounts.models import User
from apps.accounts.rbac import Action
from apps.inventory.models import InventoryAsset
from apps.machines.models import (
    Machine,
    MachineServiceRequest,
    MachineType,
    RoleMachineScope,
    RoleMachineTypeScope,
    ServiceBucket,
    ServiceQueue,
)
from apps.maintenance.models import MaintenanceSchedule
from apps.makerspaces.models import MakerspaceMembership, MakerspaceRole
from apps.warranty.models import Warranty
from tests.return_helpers import (
    authenticated_client,
    make_product,
    make_space,
    make_user,
)


pytestmark = pytest.mark.django_db
MACHINE_KEYS = {
    "scope_mode",
    "pending_prints",
    "active_prints",
    "prints_awaiting_collection",
    "warranty_expiring",
    "maintenance_overdue",
}


def _url(space):
    return f"/api/v1/admin/makerspace/{space.pk}/dashboard"


def _scoped_actor(space, username, *, types=(), machines=(), actions=None):
    actor = make_user(
        username, role=User.Role.REQUESTER, access_status=User.AccessStatus.ACTIVE
    )
    role = MakerspaceRole.objects.create(
        makerspace=space,
        name=username,
        slug=username,
        granted_actions=actions or [Action.MANAGE_MACHINES],
    )
    MakerspaceMembership.objects.create(
        user=actor,
        makerspace=space,
        role=MakerspaceMembership.Role.CUSTOM,
        assigned_role=role,
    )
    for machine_type in types:
        RoleMachineTypeScope.objects.create(role=role, machine_type=machine_type)
    for machine in machines:
        RoleMachineScope.objects.create(role=role, machine=machine)
    return actor


def _machine(space, machine_type, name):
    return Machine.objects.create(
        makerspace=space, machine_type=machine_type, name=name
    )


def _request(space, requester, status, *, queue=None, bucket=None, assigned=None):
    return MachineServiceRequest.objects.create(
        makerspace=space,
        requester=requester,
        requester_name=requester.username,
        title=f"{status}-{MachineServiceRequest.objects.count()}",
        status=status,
        queue=queue,
        bucket=bucket,
        assigned_machine=assigned,
    )


def test_restricted_dashboard_uses_every_request_path_and_machine_only_counts():
    space = make_space("phase6a-dashboard-paths")
    printer_type = MachineType.objects.get(
        makerspace__isnull=True, slug="3d_printer"
    )
    laser_type = MachineType.objects.create(
        makerspace=space, slug="phase6a-laser", name="Laser"
    )
    local_slug_collision = MachineType.objects.create(
        makerspace=space, slug="3d_printer", name="Not the built-in printer"
    )
    printer_one = _machine(space, printer_type, "Printer one")
    printer_two = _machine(space, printer_type, "Printer two")
    laser = _machine(space, laser_type, "Laser")
    local_collision = _machine(space, local_slug_collision, "Local collision")
    requester = make_user(
        "phase6a-dashboard-requester", access_status=User.AccessStatus.ACTIVE
    )
    printer_queue = ServiceQueue.objects.create(
        makerspace=space, machine_type=printer_type, name="Printer queue"
    )
    laser_queue = ServiceQueue.objects.create(
        makerspace=space, machine_type=laser_type, name="Laser queue"
    )
    collision_queue = ServiceQueue.objects.create(
        makerspace=space, machine_type=local_slug_collision, name="Collision queue"
    )
    printer_bucket = ServiceBucket.objects.create(
        machine=printer_two, name="Printer bucket"
    )
    laser_bucket = ServiceBucket.objects.create(machine=laser, name="Laser bucket")
    _request(space, requester, MachineServiceRequest.Status.PENDING, queue=printer_queue)
    _request(space, requester, MachineServiceRequest.Status.IN_PROGRESS, bucket=printer_bucket)
    _request(
        space,
        requester,
        MachineServiceRequest.Status.COMPLETED,
        queue=laser_queue,
        assigned=printer_one,
    )
    _request(space, requester, MachineServiceRequest.Status.PENDING, bucket=laser_bucket)
    _request(space, requester, MachineServiceRequest.Status.PENDING, queue=collision_queue)

    soon = timezone.localdate() + timedelta(days=1)
    Warranty.objects.create(makerspace=space, machine=printer_one, warranty_expires_on=soon)
    Warranty.objects.create(makerspace=space, machine=laser, warranty_expires_on=soon)
    asset = InventoryAsset.objects.create(
        makerspace=space,
        product=make_product(space, name="Dashboard asset"),
        asset_tag="PHASE6A-ASSET",
    )
    Warranty.objects.create(makerspace=space, asset=asset, warranty_expires_on=soon)
    for machine in (printer_one, laser):
        MaintenanceSchedule.objects.create(
            machine=machine,
            description="Overdue",
            interval_days=30,
            next_due=timezone.localdate() - timedelta(days=1),
        )

    actor = _scoped_actor(space, "phase6a-printer-team", types=[printer_type])
    response = authenticated_client(actor).get(_url(space))

    assert response.status_code == 200
    assert set(response.data) == MACHINE_KEYS
    assert response.data == {
        "scope_mode": "machine",
        "pending_prints": 1,
        "active_prints": 1,
        "prints_awaiting_collection": 1,
        "warranty_expiring": 1,
        "maintenance_overdue": 1,
    }

    collision_actor = _scoped_actor(
        space, "phase6a-collision-team", types=[local_slug_collision]
    )
    collision = authenticated_client(collision_actor).get(_url(space))
    assert collision.data["pending_prints"] == 0
    assert local_collision.machine_type.slug == "3d_printer"


def test_dashboard_assigned_role_scope_matrix_is_fail_closed_and_cumulative():
    space = make_space("phase6a-dashboard-matrix")
    first_type = MachineType.objects.create(
        makerspace=space, slug="phase6a-first", name="First"
    )
    second_type = MachineType.objects.create(
        makerspace=space, slug="phase6a-second", name="Second"
    )
    hidden_type = MachineType.objects.create(
        makerspace=space, slug="phase6a-hidden", name="Hidden"
    )
    first = _machine(space, first_type, "First")
    second = _machine(space, second_type, "Second")
    hidden = _machine(space, hidden_type, "Hidden")
    soon = timezone.localdate() + timedelta(days=1)
    for machine in (first, second, hidden):
        Warranty.objects.create(
            makerspace=space, machine=machine, warranty_expires_on=soon
        )

    actors = {
        "none": _scoped_actor(space, "phase6a-none"),
        "one": _scoped_actor(space, "phase6a-one", types=[first_type]),
        "two": _scoped_actor(
            space, "phase6a-two", types=[first_type, second_type]
        ),
        "machine": _scoped_actor(space, "phase6a-machine", machines=[second]),
    }

    counts = {
        name: authenticated_client(actor).get(_url(space)).data["warranty_expiring"]
        for name, actor in actors.items()
    }
    assert counts == {"none": 0, "one": 1, "two": 2, "machine": 1}


def test_a_mixed_role_keeps_its_inventory_tiles_but_still_loses_other_machines():
    """Roles here are editable and action-based, so authority composes.

    A custom role holding VIEW_INVENTORY *and* a scoped MANAGE_MACHINES is not a
    machine-only actor: treating "has a machine scope" as "is a maintainer" removed the
    hardware and stock counts it is independently authorized for. Scoping must narrow
    machine data without revoking another granted action.
    """
    space = make_space("phase6a-dashboard-mixed")
    own_type = MachineType.objects.create(
        makerspace=space, slug="phase6a-mixed-own", name="Own"
    )
    other_type = MachineType.objects.create(
        makerspace=space, slug="phase6a-mixed-other", name="Other"
    )
    own_machine = _machine(space, own_type, "Own")
    other_machine = _machine(space, other_type, "Other")
    soon = timezone.localdate() + timedelta(days=1)
    Warranty.objects.create(
        makerspace=space, machine=own_machine, warranty_expires_on=soon
    )
    Warranty.objects.create(
        makerspace=space, machine=other_machine, warranty_expires_on=soon
    )
    asset = InventoryAsset.objects.create(
        makerspace=space,
        product=make_product(space, name="Mixed asset"),
        asset_tag="PHASE6A-MIXED",
    )
    Warranty.objects.create(makerspace=space, asset=asset, warranty_expires_on=soon)

    mixed = _scoped_actor(
        space,
        "phase6a-mixed-actor",
        types=[own_type],
        actions=[Action.MANAGE_MACHINES, Action.VIEW_INVENTORY],
    )
    response = authenticated_client(mixed).get(_url(space))

    assert response.status_code == 200
    assert response.data["scope_mode"] == "full"
    # The inventory-derived tiles it is authorized for are present, not omitted.
    assert "overdue_loans" in response.data
    assert "low_stock" in response.data
    # ...while the other team's machine warranty is still excluded. Its own machine plus
    # the asset warranty it may see = 2; the other machine's row must not be counted.
    assert response.data["warranty_expiring"] == 2


def test_a_machine_only_role_still_sees_no_asset_warranty():
    """The complement: without inventory authority, asset warranties stay hidden."""
    space = make_space("phase6a-dashboard-machineonly")
    own_type = MachineType.objects.create(
        makerspace=space, slug="phase6a-mo-own", name="Own"
    )
    own_machine = _machine(space, own_type, "Own")
    soon = timezone.localdate() + timedelta(days=1)
    Warranty.objects.create(
        makerspace=space, machine=own_machine, warranty_expires_on=soon
    )
    asset = InventoryAsset.objects.create(
        makerspace=space,
        product=make_product(space, name="Machine-only asset"),
        asset_tag="PHASE6A-MO",
    )
    Warranty.objects.create(makerspace=space, asset=asset, warranty_expires_on=soon)

    actor = _scoped_actor(space, "phase6a-mo-actor", types=[own_type])
    response = authenticated_client(actor).get(_url(space))

    assert response.data["scope_mode"] == "machine"
    assert response.data["warranty_expiring"] == 1
    assert "low_stock" not in response.data


def test_awaiting_collection_follows_collect_authority_not_machine_scope():
    """The tile links to Handover, so it must agree with what Handover lets them do."""
    space = make_space("phase6a-dashboard-collect")
    printer_type = MachineType.objects.get(
        makerspace__isnull=True, slug="3d_printer"
    )
    laser_type = MachineType.objects.create(
        makerspace=space, slug="phase6a-collect-laser", name="Laser"
    )
    printer = _machine(space, printer_type, "Printer")
    _machine(space, laser_type, "Laser")
    requester = make_user(
        "phase6a-collect-requester", access_status=User.AccessStatus.ACTIVE
    )
    printer_bucket = ServiceBucket.objects.create(
        machine=printer, name="Printer bucket"
    )
    _request(
        space,
        requester,
        MachineServiceRequest.Status.COMPLETED,
        bucket=printer_bucket,
        assigned=printer,
    )

    implied = _scoped_actor(space, "phase6a-collect-implied", types=[laser_type])
    direct = _scoped_actor(
        space,
        "phase6a-collect-direct",
        types=[laser_type],
        actions=[Action.MANAGE_MACHINES, Action.COLLECT_SERVICE_REQUEST],
    )

    implied_counts = authenticated_client(implied).get(_url(space)).data
    direct_counts = authenticated_client(direct).get(_url(space)).data

    # Implied collect (from MANAGE_MACHINES) must not widen the count.
    assert implied_counts["prints_awaiting_collection"] == 0
    # A DIRECT grant makes that printer job collectable, so it must be counted.
    assert direct_counts["prints_awaiting_collection"] == 1
    # Widening collection must not widen the machine-management counters.
    assert direct_counts["pending_prints"] == 0
    assert direct_counts["active_prints"] == 0


def test_dashboard_full_mode_exempts_assigned_space_manager_superadmin_and_legacy():
    space = make_space("phase6a-dashboard-exempt")
    assigned = make_user(
        "phase6a-assigned-space", access_status=User.AccessStatus.ACTIVE
    )
    MakerspaceMembership.objects.create(
        user=assigned,
        makerspace=space,
        role=MakerspaceMembership.Role.SPACE_MANAGER,
        assigned_role=MakerspaceRole.objects.get(
            makerspace=space, slug="space_manager"
        ),
    )
    legacy = make_user("phase6a-legacy", access_status=User.AccessStatus.ACTIVE)
    MakerspaceMembership.objects.create(
        user=legacy,
        makerspace=space,
        role=MakerspaceMembership.Role.MACHINE_MANAGER,
        assigned_role=None,
    )
    superadmin = make_user(
        "phase6a-superadmin",
        role=User.Role.SUPERADMIN,
        access_status=User.AccessStatus.ACTIVE,
        is_staff=True,
        is_superuser=True,
    )

    for actor in (assigned, superadmin, legacy):
        response = authenticated_client(actor).get(_url(space))
        assert response.status_code == 200
        assert response.data["scope_mode"] == "full"
        assert "overdue_loans" in response.data
