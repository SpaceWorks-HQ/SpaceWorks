"""Cumulative direct collection without widening machine lifecycle authority."""

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.accounts.rbac import Action
from apps.machines import role_scope
from apps.machines.models import (
    Machine,
    MachineServiceRequest,
    MachineType,
    RoleMachineScope,
    RoleMachineTypeScope,
    ServiceBucket,
    ServiceRequestFile,
)
from apps.makerspaces.models import MakerspaceMembership, MakerspaceRole
from tests.return_helpers import authenticated_client, make_space, make_user


pytestmark = pytest.mark.django_db


def _actor(space, username, machine_type=None, *, machine=None, direct_collect):
    actor = make_user(
        username, role=User.Role.REQUESTER, access_status=User.AccessStatus.ACTIVE
    )
    actions = [Action.MANAGE_MACHINES]
    if direct_collect:
        actions.append(Action.COLLECT_SERVICE_REQUEST)
    role = MakerspaceRole.objects.create(
        makerspace=space,
        name=username,
        slug=username,
        granted_actions=actions,
    )
    if machine_type is not None:
        RoleMachineTypeScope.objects.create(role=role, machine_type=machine_type)
    if machine is not None:
        RoleMachineScope.objects.create(role=role, machine=machine)
    MakerspaceMembership.objects.create(
        user=actor,
        makerspace=space,
        role=MakerspaceMembership.Role.CUSTOM,
        assigned_role=role,
    )
    return actor


def _request(space, machine, requester, status, title):
    bucket, _ = ServiceBucket.objects.get_or_create(
        machine=machine, name="Phase 6a service"
    )
    return MachineServiceRequest.objects.create(
        makerspace=space,
        bucket=bucket,
        assigned_machine=machine,
        requester=requester,
        requester_name=requester.username,
        title=title,
        status=status,
    )


def _list_url(space):
    return reverse(
        "admin-machine-service-request-list-create", args=[space.pk]
    )


def _detail_url(row):
    return reverse("admin-machine-service-request-detail", args=[row.pk])


def _action_url(row, action):
    return reverse(f"admin-machine-service-request-{action}", args=[row.pk])


def test_hybrid_direct_collect_unions_completed_rows_but_not_management_or_files():
    space = make_space("phase6a-hybrid-collect")
    laser_type = MachineType.objects.create(
        makerspace=space, slug="phase6a-hybrid-laser", name="Laser"
    )
    printer_type = MachineType.objects.get(
        makerspace__isnull=True, slug="3d_printer"
    )
    laser = Machine.objects.create(
        makerspace=space, machine_type=laser_type, name="Laser"
    )
    printer = Machine.objects.create(
        makerspace=space, machine_type=printer_type, name="Printer"
    )
    requester = make_user(
        "phase6a-hybrid-requester", access_status=User.AccessStatus.ACTIVE
    )
    own_pending = _request(
        space, laser, requester, MachineServiceRequest.Status.PENDING, "Own pending"
    )
    other_completed = _request(
        space,
        printer,
        requester,
        MachineServiceRequest.Status.COMPLETED,
        "Other completed",
    )
    other_pending = _request(
        space,
        printer,
        requester,
        MachineServiceRequest.Status.PENDING,
        "Other pending",
    )
    attached = ServiceRequestFile.objects.create(
        service_request=other_completed,
        makerspace=space,
        machine=printer,
        kind=ServiceRequestFile.Kind.ATTACHMENT,
        object_key="phase6a/hybrid/other.pdf",
        original_filename="other.pdf",
        owner_user_id=requester.pk,
        attached_at=timezone.now(),
    )
    actor = _actor(
        space, "phase6a-hybrid-actor", laser_type, direct_collect=True
    )
    client = authenticated_client(actor)

    listed = client.get(_list_url(space))
    assert listed.status_code == 200
    assert {row["id"] for row in listed.data} == {
        own_pending.pk,
        other_completed.pk,
    }
    assert client.get(_detail_url(other_completed)).status_code == 200
    assert client.get(_detail_url(other_pending)).status_code == 404
    assert client.post(
        _action_url(other_completed, "reprint"), {}, format="json"
    ).status_code == 404
    assert client.get(
        reverse("admin-machine-service-file-url", args=[attached.pk])
    ).status_code == 404

    collected = client.post(
        _action_url(other_completed, "collect"), {}, format="json"
    )
    other_completed.refresh_from_db()
    assert collected.status_code == 200
    assert other_completed.status == MachineServiceRequest.Status.COLLECTED
    assert other_completed.collected_by_id == actor.pk


def test_implied_collect_does_not_add_completed_rows_outside_machine_scope():
    space = make_space("phase6a-implied-collect")
    laser_type = MachineType.objects.create(
        makerspace=space, slug="phase6a-implied-laser", name="Laser"
    )
    printer_type = MachineType.objects.create(
        makerspace=space, slug="phase6a-implied-printer", name="Printer"
    )
    laser = Machine.objects.create(
        makerspace=space, machine_type=laser_type, name="Laser"
    )
    printer = Machine.objects.create(
        makerspace=space, machine_type=printer_type, name="Printer"
    )
    requester = make_user(
        "phase6a-implied-requester", access_status=User.AccessStatus.ACTIVE
    )
    own = _request(
        space, laser, requester, MachineServiceRequest.Status.PENDING, "Own"
    )
    hidden = _request(
        space,
        printer,
        requester,
        MachineServiceRequest.Status.COMPLETED,
        "Hidden complete",
    )
    actor = _actor(
        space, "phase6a-implied-actor", laser_type, direct_collect=False
    )
    client = authenticated_client(actor)

    listed = client.get(_list_url(space))
    assert {row["id"] for row in listed.data} == {own.pk}
    assert client.get(_detail_url(hidden)).status_code == 404
    assert client.post(
        _action_url(hidden, "collect"), {}, format="json"
    ).status_code == 404


def test_a_hidden_space_superadmin_does_not_widen_on_an_IMPLIED_collect_grant():
    """A hard-hidden space reduces a superadmin to their membership role's authority.

    `role_scope.grants_directly` short-circuits on superadmin status, and
    `superadmin_hidden_block_applies` resolves through `actions_for_membership`, which
    EXPANDS implied actions -- so `MANAGE_MACHINES` implying `COLLECT_SERVICE_REQUEST`
    made the union's second arm fire for a role that never stored it, handing back the
    makerspace-wide completed rows the role's machine links exist to deny.
    """
    space = make_space("phase6a-hidden-super")
    space.superadmin_access_enabled = False
    space.save(update_fields=["superadmin_access_enabled"])
    laser_type = MachineType.objects.create(
        makerspace=space, slug="phase6a-hidden-laser", name="Laser"
    )
    printer_type = MachineType.objects.create(
        makerspace=space, slug="phase6a-hidden-printer", name="Printer"
    )
    laser = Machine.objects.create(
        makerspace=space, machine_type=laser_type, name="Laser"
    )
    printer = Machine.objects.create(
        makerspace=space, machine_type=printer_type, name="Printer"
    )
    requester = make_user(
        "phase6a-hidden-requester", access_status=User.AccessStatus.ACTIVE
    )
    own = _request(
        space, laser, requester, MachineServiceRequest.Status.PENDING, "Own"
    )
    other_completed = _request(
        space, printer, requester, MachineServiceRequest.Status.COMPLETED, "Other"
    )
    superadmin = make_user(
        "phase6a-hidden-super-actor",
        role=User.Role.SUPERADMIN,
        access_status=User.AccessStatus.ACTIVE,
        is_staff=True,
        is_superuser=True,
    )
    role = MakerspaceRole.objects.create(
        makerspace=space,
        name="Hidden laser",
        slug="phase6a-hidden-laser-role",
        granted_actions=[Action.MANAGE_MACHINES],
    )
    RoleMachineTypeScope.objects.create(role=role, machine_type=laser_type)
    MakerspaceMembership.objects.create(
        user=superadmin,
        makerspace=space,
        role=MakerspaceMembership.Role.CUSTOM,
        assigned_role=role,
    )

    # The two helpers must disagree, and that disagreement is the whole fix.
    assert role_scope.grants_directly(
        superadmin, space.pk, Action.COLLECT_SERVICE_REQUEST
    )
    assert not role_scope.role_grants_directly(
        superadmin, space.pk, Action.COLLECT_SERVICE_REQUEST
    )

    client = authenticated_client(superadmin)
    listed = client.get(_list_url(space))

    assert listed.status_code == 200
    assert {row["id"] for row in listed.data} == {own.pk}
    assert client.get(_detail_url(other_completed)).status_code == 404
    assert client.post(
        _action_url(other_completed, "collect"), {}, format="json"
    ).status_code == 404


def test_handover_management_partition_assigned_scope_matrix_and_exemptions():
    space = make_space("phase6a-handover-matrix")
    types = [
        MachineType.objects.create(
            makerspace=space, slug=f"phase6a-matrix-{index}", name=f"Type {index}"
        )
        for index in range(3)
    ]
    machines = [
        Machine.objects.create(
            makerspace=space, machine_type=machine_type, name=f"Machine {index}"
        )
        for index, machine_type in enumerate(types)
    ]
    requester = make_user(
        "phase6a-matrix-requester", access_status=User.AccessStatus.ACTIVE
    )
    rows = [
        _request(
            space,
            machine,
            requester,
            MachineServiceRequest.Status.PENDING,
            f"Job {index}",
        )
        for index, machine in enumerate(machines)
    ]
    no_links = _actor(
        space, "phase6a-matrix-none", direct_collect=False
    )
    one_type = _actor(
        space, "phase6a-matrix-one", types[0], direct_collect=False
    )
    two_types = _actor(
        space, "phase6a-matrix-two", types[0], direct_collect=False
    )
    two_role = two_types.makerspace_memberships.get(
        makerspace=space
    ).assigned_role
    RoleMachineTypeScope.objects.create(role=two_role, machine_type=types[1])
    one_machine = _actor(
        space,
        "phase6a-matrix-machine",
        machine=machines[1],
        direct_collect=False,
    )

    expected = {
        no_links: set(),
        one_type: {rows[0].pk},
        two_types: {rows[0].pk, rows[1].pk},
        one_machine: {rows[1].pk},
    }
    for actor, visible_ids in expected.items():
        response = authenticated_client(actor).get(_list_url(space))
        assert response.status_code == 200
        assert {row["id"] for row in response.data} == visible_ids
    assert authenticated_client(one_type).get(_detail_url(rows[2])).status_code == 404

    assigned_space_manager = make_user(
        "phase6a-matrix-space", access_status=User.AccessStatus.ACTIVE
    )
    MakerspaceMembership.objects.create(
        user=assigned_space_manager,
        makerspace=space,
        role=MakerspaceMembership.Role.SPACE_MANAGER,
        assigned_role=MakerspaceRole.objects.get(
            makerspace=space, slug="space_manager"
        ),
    )
    legacy = make_user(
        "phase6a-matrix-legacy", access_status=User.AccessStatus.ACTIVE
    )
    MakerspaceMembership.objects.create(
        user=legacy,
        makerspace=space,
        role=MakerspaceMembership.Role.MACHINE_MANAGER,
        assigned_role=None,
    )
    superadmin = make_user(
        "phase6a-matrix-super",
        role=User.Role.SUPERADMIN,
        access_status=User.AccessStatus.ACTIVE,
        is_staff=True,
        is_superuser=True,
    )
    all_ids = {row.pk for row in rows}
    for actor in (assigned_space_manager, legacy, superadmin):
        response = authenticated_client(actor).get(_list_url(space))
        assert {row["id"] for row in response.data} == all_ids
