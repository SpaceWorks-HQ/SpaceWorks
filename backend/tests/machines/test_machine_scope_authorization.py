"""Authorization regressions for machine-scoped staff service surfaces."""

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.accounts.rbac import Action
from apps.machines.models import (
    Machine,
    MachineConsumablePool,
    MachineServiceRequest,
    MachineType,
    MachineUsageEntry,
    RoleMachineScope,
    RoleMachineTypeScope,
    ServiceBucket,
    ServiceQueue,
)
from apps.makerspaces.models import Makerspace, MakerspaceMembership, MakerspaceRole

pytestmark = pytest.mark.django_db


def _client(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _user(username):
    return User.objects.create_user(
        username=username,
        email=f"{username}@example.test",
        role=User.Role.REQUESTER,
        access_status=User.AccessStatus.ACTIVE,
    )


def _manager(space, username, *, machine_type=None, machine=None):
    actor = _user(username)
    role = MakerspaceRole.objects.create(
        makerspace=space,
        name=username,
        slug=username,
        granted_actions=[Action.MANAGE_MACHINES],
    )
    MakerspaceMembership.objects.create(
        user=actor,
        makerspace=space,
        role=MakerspaceMembership.Role.CUSTOM,
        assigned_role=role,
    )
    if machine_type is not None:
        RoleMachineTypeScope.objects.create(role=role, machine_type=machine_type)
    if machine is not None:
        RoleMachineScope.objects.create(role=role, machine=machine)
    return actor


@pytest.fixture
def scoped_lab():
    space = Makerspace.objects.create(name="Scoped service lab", slug="scoped-service-lab")
    printer_type = MachineType.objects.create(
        makerspace=space, slug="scope-printer", name="Printer"
    )
    laser_type = MachineType.objects.create(
        makerspace=space, slug="scope-laser", name="Laser"
    )
    printer = Machine.objects.create(
        makerspace=space, machine_type=printer_type, name="Printer"
    )
    laser = Machine.objects.create(
        makerspace=space, machine_type=laser_type, name="Laser"
    )
    return {
        "space": space,
        "printer_type": printer_type,
        "laser_type": laser_type,
        "printer": printer,
        "laser": laser,
        "laser_manager": _manager(
            space, "scope-laser-manager", machine_type=laser_type
        ),
    }


def _service_request(space, machine, *, status=MachineServiceRequest.Status.COMPLETED):
    bucket, _ = ServiceBucket.objects.get_or_create(machine=machine, name="Service")
    requester = _user(f"requester-{machine.pk}-{MachineServiceRequest.objects.count()}")
    return MachineServiceRequest.objects.create(
        makerspace=space,
        bucket=bucket,
        requester=requester,
        assigned_machine=machine,
        title="Scoped job",
        status=status,
    )


def _usage_payload(machine, **overrides):
    payload = {
        "machine_id": machine.pk,
        "duration_minutes": 10,
        "outcome": "success",
    }
    payload.update(overrides)
    return payload


def test_manual_usage_list_returns_only_entries_for_scoped_machines(scoped_lab):
    laser_entry = MachineUsageEntry.objects.create(
        machine=scoped_lab["laser"],
        source=MachineUsageEntry.Source.TYPED_MANUAL,
        duration_minutes=10,
        outcome="success",
    )
    MachineUsageEntry.objects.create(
        machine=scoped_lab["printer"],
        source=MachineUsageEntry.Source.TYPED_MANUAL,
        duration_minutes=10,
        outcome="success",
    )
    url = reverse(
        "admin-machine-service-printer-typed-manual-usage",
        args=[scoped_lab["space"].pk],
    )

    response = _client(scoped_lab["laser_manager"]).get(
        url, {"machine_type": scoped_lab["laser_type"].slug}
    )

    assert response.status_code == 200
    assert {row["id"] for row in response.data} == {laser_entry.pk}


def test_manual_usage_submission_rejects_an_out_of_scope_machine(scoped_lab):
    url = reverse(
        "admin-machine-service-printer-typed-manual-usage",
        args=[scoped_lab["space"].pk],
    )

    response = _client(scoped_lab["laser_manager"]).post(
        url, _usage_payload(scoped_lab["printer"]), format="json"
    )

    assert response.status_code == 404
    assert not MachineUsageEntry.objects.filter(
        machine=scoped_lab["printer"], source=MachineUsageEntry.Source.TYPED_MANUAL
    ).exists()


def test_manual_usage_submission_rejects_out_of_scope_service_request(scoped_lab):
    printer_request = _service_request(scoped_lab["space"], scoped_lab["printer"])
    url = reverse(
        "admin-machine-service-printer-typed-manual-usage",
        args=[scoped_lab["space"].pk],
    )

    response = _client(scoped_lab["laser_manager"]).post(
        url,
        _usage_payload(
            scoped_lab["laser"], service_request_id=printer_request.pk
        ),
        format="json",
    )

    assert response.status_code == 404
    assert not MachineUsageEntry.objects.filter(service_request=printer_request).exists()


def test_pool_creation_rejects_an_out_of_scope_bound_machine(scoped_lab):
    url = reverse("admin-machine-service-printer-pools", args=[scoped_lab["space"].pk])

    response = _client(scoped_lab["laser_manager"]).post(
        url,
        {"machine_id": scoped_lab["printer"].pk, "material": "PLA", "quantity": "100"},
        format="json",
    )

    assert response.status_code == 404
    assert not MachineConsumablePool.objects.filter(machine=scoped_lab["printer"]).exists()


def test_shared_pool_creation_remains_allowed_for_scoped_manager(scoped_lab):
    url = reverse("admin-machine-service-printer-pools", args=[scoped_lab["space"].pk])

    response = _client(scoped_lab["laser_manager"]).post(
        url, {"material": "Shared stock", "quantity": "100"}, format="json"
    )

    assert response.status_code == 201
    assert MachineConsumablePool.objects.get(pk=response.data["id"]).machine_id is None


def test_staff_service_submission_rejects_an_out_of_scope_machine(scoped_lab):
    member = _user("scope-service-member")
    MakerspaceMembership.objects.create(
        user=member,
        makerspace=scoped_lab["space"],
        role=MakerspaceMembership.Role.INVENTORY_MANAGER,
    )
    url = reverse(
        "admin-machine-service-request-list-create", args=[scoped_lab["space"].pk]
    )

    response = _client(scoped_lab["laser_manager"]).post(
        url,
        {
            "requester_id": member.pk,
            "machine_id": scoped_lab["printer"].pk,
            "title": "Unauthorized printer job",
        },
        format="json",
    )

    assert response.status_code == 404
    assert not MachineServiceRequest.objects.filter(title="Unauthorized printer job").exists()


def test_explicit_start_rejects_out_of_scope_machine_without_state_changes(scoped_lab):
    request = _service_request(
        scoped_lab["space"],
        scoped_lab["laser"],
        status=MachineServiceRequest.Status.ACCEPTED,
    )
    url = reverse("admin-machine-service-request-start", args=[request.pk])

    response = _client(scoped_lab["laser_manager"]).post(
        url, {"machine_id": scoped_lab["printer"].pk}, format="json"
    )

    request.refresh_from_db()
    scoped_lab["laser"].refresh_from_db()
    scoped_lab["printer"].refresh_from_db()
    assert (response.status_code, response.data["code"]) == (
        409,
        "service_machine_unavailable",
    )
    assert request.status == MachineServiceRequest.Status.ACCEPTED
    assert request.assigned_machine_id == scoped_lab["laser"].pk
    assert scoped_lab["laser"].status == Machine.Status.IDLE
    assert scoped_lab["printer"].status == Machine.Status.IDLE


def test_first_idle_skips_earlier_unauthorized_machine(scoped_lab):
    queue = ServiceQueue.objects.create(
        makerspace=scoped_lab["space"],
        machine_type=scoped_lab["laser_type"],
        name="First idle",
        allocation_policy=ServiceQueue.AllocationPolicy.FIRST_IDLE,
    )
    authorized = Machine.objects.create(
        makerspace=scoped_lab["space"],
        machine_type=scoped_lab["laser_type"],
        name="Later authorized laser",
    )
    actor = _manager(
        scoped_lab["space"], "scope-one-machine-manager", machine=authorized
    )
    requester = _user("scope-first-idle-requester")
    request = MachineServiceRequest.objects.create(
        makerspace=scoped_lab["space"],
        queue=queue,
        requester=requester,
        assigned_machine=authorized,
        title="First idle scoped job",
        status=MachineServiceRequest.Status.ACCEPTED,
    )
    assert scoped_lab["laser"].pk < authorized.pk

    response = _client(actor).post(
        reverse("admin-machine-service-request-start", args=[request.pk]),
        {},
        format="json",
    )

    request.refresh_from_db()
    scoped_lab["laser"].refresh_from_db()
    authorized.refresh_from_db()
    assert response.status_code == 200
    assert request.assigned_machine_id == authorized.pk
    assert scoped_lab["laser"].status == Machine.Status.IDLE
    assert authorized.status == Machine.Status.RUNNING


def test_service_requests_filter_by_machine_type_id_not_slug(scoped_lab):
    """A slug is not unique across the global/tenant split.

    A makerspace may create a local type whose slug equals a global built-in's. Filtering
    service data by slug then returns BOTH types' rows, so the console shows one type's jobs
    under another and a manager can accept or reject from the wrong section.
    """
    space = scoped_lab["space"]
    # Slug uniqueness is SCOPED (`uniq_global_machinetype_slug` / `uniq_lab_machinetype_slug`),
    # so a makerspace-local type may legally carry a global built-in's slug. A global type must
    # also be `is_builtin` per `machinetype_builtin_is_global`.
    global_type = MachineType.objects.create(
        makerspace=None, slug="shared-slug", name="Global", is_builtin=True
    )
    local_type = MachineType.objects.create(makerspace=space, slug="shared-slug", name="Local")
    global_machine = Machine.objects.create(makerspace=space, machine_type=global_type, name="G")
    local_machine = Machine.objects.create(makerspace=space, machine_type=local_type, name="L")
    _service_request(space, global_machine)
    _service_request(space, local_machine)
    manager = _manager(space, "collision-manager", machine_type=global_type)
    RoleMachineTypeScope.objects.create(
        role=manager.makerspace_memberships.get().assigned_role, machine_type=local_type
    )

    url = reverse("admin-machine-service-request-list-create", args=[space.pk])
    response = _client(manager).get(f"{url}?machine_type_id={global_type.pk}")

    assert response.status_code == 200
    returned = {row["id"] for row in response.json()}
    only_global = {
        row.pk
        for row in MachineServiceRequest.objects.filter(assigned_machine=global_machine)
    }
    assert returned == only_global
