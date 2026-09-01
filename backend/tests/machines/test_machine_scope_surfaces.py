"""Cross-scope leak tests for the makerspace-level machine surfaces (Phase 3).

Every one of these surfaces was gated on ``MANAGE_MACHINES`` alone, which is
makerspace-wide -- so a role scoped to the laser cutters could read every printer job in
the lab, its costs, its uploaded CAD and its requester's contact details. These assert
the narrowing from the *other* team's point of view: the laser manager must not see the
printer's rows, and the printer manager must still see their own.

A surface that regresses fails here rather than passing quietly, which is the whole
reason the tests are written per surface instead of once over a helper.
"""

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
    RoleMachineTypeScope,
    ServiceBucket,
)
from apps.makerspaces.models import Makerspace, MakerspaceMembership, MakerspaceRole
from apps.payments.models import Payment

pytestmark = pytest.mark.django_db


@pytest.fixture
def lab():
    """A makerspace with a printer and a laser, and a manager scoped to each."""
    space = Makerspace.objects.create(name="two-team-lab", slug="two-team-lab")
    printers = MachineType.objects.create(
        slug="tt-printer", name="Printer", makerspace=space
    )
    lasers = MachineType.objects.create(
        slug="tt-laser", name="Laser", makerspace=space
    )
    printer = Machine.objects.create(
        makerspace=space, machine_type=printers, name="Prusa"
    )
    laser = Machine.objects.create(
        makerspace=space, machine_type=lasers, name="Glowforge"
    )

    def manager(username, machine_type):
        user = User.objects.create_user(
            username=username,
            email=f"{username}@e.com",
            role=User.Role.REQUESTER,
            access_status=User.AccessStatus.ACTIVE,
        )
        role = MakerspaceRole.objects.create(
            makerspace=space,
            name=username.title(),
            slug=username,
            granted_actions=[Action.MANAGE_MACHINES],
        )
        RoleMachineTypeScope.objects.create(role=role, machine_type=machine_type)
        MakerspaceMembership.objects.create(
            user=user,
            makerspace=space,
            role=MakerspaceMembership.Role.CUSTOM,
            assigned_role=role,
        )
        return user

    return {
        "space": space,
        "printer": printer,
        "laser": laser,
        "printer_type": printers,
        "laser_type": lasers,
        "printer_mgr": manager("printer-team", printers),
        "laser_mgr": manager("laser-team", lasers),
    }


def _ids(body):
    """Ids from a list endpoint, paginated or not."""
    rows = body.get("results", body) if isinstance(body, dict) else body
    return {row["id"] for row in rows}


def client_for(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def make_request_on(lab, machine, requester_name="job-requester"):
    # bucket XOR queue is a check constraint; the bucket also names the machine, which is
    # one of the routes `role_scope` follows to decide who owns the job.
    bucket, _ = ServiceBucket.objects.get_or_create(machine=machine, name="default")
    requester = User.objects.create_user(
        username=f"{requester_name}-{machine.pk}",
        email=f"{requester_name}-{machine.pk}@e.com",
        role=User.Role.REQUESTER,
        access_status=User.AccessStatus.ACTIVE,
    )
    return MachineServiceRequest.objects.create(
        makerspace=lab["space"],
        requester=requester,
        assigned_machine=machine,
        bucket=bucket,
        status=MachineServiceRequest.Status.COMPLETED,
    )


def test_the_service_queue_hides_the_other_team_s_jobs(lab):
    printer_job = make_request_on(lab, lab["printer"])
    laser_job = make_request_on(lab, lab["laser"])

    url = reverse("admin-machine-service-request-list-create", args=[lab["space"].id])
    listed = _ids(client_for(lab["laser_mgr"]).get(url).json())

    assert laser_job.pk in listed
    assert printer_job.pk not in listed


def test_the_warranty_report_hides_the_other_team_s_machine_rows(lab):
    """Regression: the existing report keeps its machine-access partition."""
    response = client_for(lab["laser_mgr"]).get(
        reverse("admin-makerspace-warranties", args=[lab["space"].pk])
    )

    assert response.status_code == 200
    rows = response.json()["results"]
    assert {(row["host_kind"], row["host_id"]) for row in rows} == {
        ("machine", lab["laser"].pk)
    }


def test_a_service_request_detail_is_404_for_the_other_team(lab):
    printer_job = make_request_on(lab, lab["printer"])

    response = client_for(lab["laser_mgr"]).get(
        reverse("admin-machine-service-request-detail", args=[printer_job.pk])
    )

    assert response.status_code == 404


def test_a_scoped_manager_still_reaches_their_own_job(lab):
    printer_job = make_request_on(lab, lab["printer"])

    response = client_for(lab["printer_mgr"]).get(
        reverse("admin-machine-service-request-detail", args=[printer_job.pk])
    )

    assert response.status_code == 200


def test_consumable_pools_are_scoped_to_the_owning_machine(lab):
    printer_pool = MachineConsumablePool.objects.create(
        makerspace=lab["space"], machine=lab["printer"], material="PLA", color="black",
        initial_grams="1000.00", remaining_grams="1000.00"
    )
    laser_pool = MachineConsumablePool.objects.create(
        makerspace=lab["space"], machine=lab["laser"], material="Ply", color="natural",
        initial_grams="1000.00", remaining_grams="1000.00"
    )

    url = reverse("admin-machine-service-printer-pools", args=[lab["space"].id])
    listed = {row["id"] for row in client_for(lab["laser_mgr"]).get(url).json()}

    assert laser_pool.pk in listed
    assert printer_pool.pk not in listed


def test_shared_stock_with_no_machine_stays_visible_to_both_teams(lab):
    # Deliberate: pool rows with no machine belong to no team. Hiding them would make
    # shared filament unmanageable by everyone rather than by the wrong people.
    shared = MachineConsumablePool.objects.create(
        makerspace=lab["space"], machine=None, material="PLA", color="grey",
        initial_grams="1000.00", remaining_grams="1000.00"
    )

    url = reverse("admin-machine-service-printer-pools", args=[lab["space"].id])

    for actor in (lab["printer_mgr"], lab["laser_mgr"]):
        listed = {row["id"] for row in client_for(actor).get(url).json()}
        assert shared.pk in listed


def test_a_machine_payment_is_404_for_the_other_team(lab):
    printer_job = make_request_on(lab, lab["printer"])
    payment = Payment.objects.create(
        makerspace=lab["space"],
        subject_type=Payment.SubjectType.MACHINE_SERVICE_REQUEST,
        subject_id=printer_job.pk,
        amount="10.00",
        currency="usd",
        created_by=lab["printer_mgr"],
        status=Payment.Status.PENDING,
    )

    response = client_for(lab["laser_mgr"]).post(
        reverse("admin-machine-service-payment-mark-offline", args=[payment.pk]), {}, format="json"
    )

    assert response.status_code == 404


def test_machine_publicity_is_hidden_from_the_other_team(lab):
    # 404, not 403: `resolve_machine` runs the Phase-2 machine scoping first, so an
    # out-of-scope machine is not the actor's to know exists. That is the stricter of the
    # two answers and matches the detail-lookup convention elsewhere in the codebase.
    response = client_for(lab["laser_mgr"]).get(
        reverse("admin-machine-publicity", args=[lab["printer"].pk])
    )

    assert response.status_code == 404


def test_the_machine_service_report_only_counts_the_team_s_own_machines(lab):
    make_request_on(lab, lab["printer"])
    make_request_on(lab, lab["laser"])

    url = reverse("admin-makerspace-machine-service-report", args=[lab["space"].id])
    body = client_for(lab["laser_mgr"]).get(url).json()
    names = {
        row.get("machine_name")
        for section in body.values()
        if isinstance(section, list)
        for row in section
        if isinstance(row, dict)
    }

    assert "Prusa" not in names


def test_a_space_manager_still_sees_the_whole_lab(lab):
    # The exemption must hold end to end, or the narrowing is a regression rather than a
    # feature: a space manager's report and queue are unchanged.
    printer_job = make_request_on(lab, lab["printer"])
    laser_job = make_request_on(lab, lab["laser"])
    boss = User.objects.create_user(
        username="lab-boss",
        email="lab-boss@e.com",
        role=User.Role.REQUESTER,
        access_status=User.AccessStatus.ACTIVE,
    )
    MakerspaceMembership.objects.create(
        user=boss,
        makerspace=lab["space"],
        role=MakerspaceMembership.Role.SPACE_MANAGER,
    )

    url = reverse("admin-machine-service-request-list-create", args=[lab["space"].id])
    listed = _ids(client_for(boss).get(url).json())

    assert {printer_job.pk, laser_job.pk} <= listed
