"""Every machine-pk surface, swept with real roles rather than a helper.

`test_machine_scope_surfaces.py` covers the makerspace-level surfaces narrowed in Phase 3
(the queue, warranty, pools, payments, publicity, reports). This file covers the *other*
half: the per-machine endpoints reached by `machines/<pk>/...`, plus the maintenance
surfaces that hang off a machine through `maintenance/views_shared.require_machine_access`.

Written as a sweep on purpose. Each of these surfaces resolves its machine independently,
so the failure mode is one endpoint forgetting to ask -- and a per-surface test that has to
be remembered is exactly what gets skipped when an endpoint is added. Reaching another
team's machine here would expose its documents, its uploaded CAD, its consumable stock, its
operator roster and its maintenance history.

The roles are real `MakerspaceRole` rows with real `RoleMachineTypeScope` links, driven
through the HTTP layer, because `role_scope` narrowing is only worth anything if the views
actually apply it.
"""

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.accounts.rbac import Action
from apps.machines.models import Machine, MachineType, RoleMachineTypeScope
from apps.maintenance.models import MaintenanceSchedule
from apps.makerspaces.models import Makerspace, MakerspaceMembership, MakerspaceRole

pytestmark = pytest.mark.django_db

# A denial is 403 (in the space, not authorized for this machine) or 404 (the scoped
# queryset simply does not contain the row). Both are correct; which one a surface
# returns depends on whether it filters or checks, and pinning the exact code per surface
# would make this a test of implementation detail rather than of the boundary.
DENIED = {403, 404}


@pytest.fixture
def lab():
    """One space, two machine types, one manager scoped to each type."""
    space = Makerspace.objects.create(name="sweep-lab", slug="sweep-lab")
    printer_type = MachineType.objects.create(
        slug="sweep-printer", name="Printer", makerspace=space
    )
    laser_type = MachineType.objects.create(
        slug="sweep-laser", name="Laser", makerspace=space
    )
    printer = Machine.objects.create(
        makerspace=space, machine_type=printer_type, name="Prusa"
    )
    laser = Machine.objects.create(
        makerspace=space, machine_type=laser_type, name="Glowforge"
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
        "printer_type": printer_type,
        "laser_type": laser_type,
        "laser_mgr": manager("sweep-laser-team", laser_type),
        "printer_mgr": manager("sweep-printer-team", printer_type),
    }


def client_for(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


# (route name, extra reverse kwargs beyond the machine pk) for read surfaces that take a
# bare machine pk. Read surfaces are asserted in BOTH directions: denial alone would pass
# against an endpoint that is broken for everyone.
MACHINE_PK_READS = [
    "admin-machine-detail",
    "admin-machine-usage",
    "admin-machine-consumables",
    "admin-machine-consumable-candidates",
    "admin-machine-operators",
    "admin-machine-operator-candidates",
    "admin-machine-documents",
]


@pytest.mark.parametrize("route", MACHINE_PK_READS)
def test_a_machine_read_surface_is_denied_for_the_other_team(lab, route):
    other = client_for(lab["laser_mgr"]).get(reverse(route, args=[lab["printer"].pk]))

    assert other.status_code in DENIED, (
        f"{route} exposed the printer team's machine to the laser manager"
    )


@pytest.mark.parametrize("route", MACHINE_PK_READS)
def test_the_same_read_surface_still_works_on_the_team_s_own_machine(lab, route):
    own = client_for(lab["laser_mgr"]).get(reverse(route, args=[lab["laser"].pk]))

    assert own.status_code not in DENIED, (
        f"{route} denied the laser manager their own machine"
    )


# Mutations are asserted in the denied direction only: the point is that the boundary
# holds, and driving each one positively would need per-surface valid payloads without
# testing anything this file is about.
MACHINE_PK_MUTATIONS = [
    ("admin-machine-set-status", "post", {"status": "idle"}),
    ("admin-machine-retire", "post", {}),
    ("admin-machine-unretire", "post", {}),
    ("admin-machine-publicity", "patch", {"is_public": True}),
    ("admin-machine-document-presign", "post", {}),
    ("admin-machine-image", "post", {}),
]


@pytest.mark.parametrize("route,method,payload", MACHINE_PK_MUTATIONS)
def test_a_machine_mutation_is_denied_for_the_other_team(lab, route, method, payload):
    client = client_for(lab["laser_mgr"])
    response = getattr(client, method)(
        reverse(route, args=[lab["printer"].pk]), payload, format="json"
    )

    # A 405 is NOT a denial -- it means the wrong verb was used and the request never
    # reached the authorization check, so accepting it here would make this test vacuous.
    assert response.status_code != 405, f"{route} does not accept {method.upper()}"
    assert response.status_code in DENIED, (
        f"{route} let the laser manager act on the printer team's machine"
    )
    # A refused mutation must also have changed nothing: several of these surfaces act
    # before they serialize, so a 403 alone does not prove the row survived untouched.
    lab["printer"].refresh_from_db()
    assert lab["printer"].is_active is True
    assert lab["printer"].is_public is False
    assert lab["printer"].status == Machine.Status.IDLE


def test_the_machine_list_shows_only_the_team_s_own_machines(lab):
    listed = client_for(lab["laser_mgr"]).get(
        reverse("admin-machines", args=[lab["space"].pk])
    )

    assert listed.status_code == 200
    assert {row["id"] for row in listed.json()["results"]} == {lab["laser"].pk}


def test_maintenance_schedules_are_scoped_to_the_team_s_machines(lab):
    """A schedule names a machine, so reading another team's is reading their history."""
    laser_client = client_for(lab["laser_mgr"])

    other = laser_client.get(
        reverse(
            "admin-maintenance-schedule-list-create",
            args=[lab["space"].pk, lab["printer"].pk],
        )
    )
    own = laser_client.get(
        reverse(
            "admin-maintenance-schedule-list-create",
            args=[lab["space"].pk, lab["laser"].pk],
        )
    )

    assert other.status_code in DENIED
    assert own.status_code not in DENIED


def test_creating_a_maintenance_schedule_on_another_team_s_machine_is_refused(lab):
    before = MaintenanceSchedule.objects.count()

    response = client_for(lab["laser_mgr"]).post(
        reverse(
            "admin-maintenance-schedule-list-create",
            args=[lab["space"].pk, lab["printer"].pk],
        ),
        {
            "description": "Sweep",
            "interval_days": 30,
            "next_due": timezone.localdate().isoformat(),
        },
        format="json",
    )

    assert response.status_code in DENIED
    assert MaintenanceSchedule.objects.count() == before


def test_a_maintenance_schedule_detail_is_denied_by_its_machine_not_its_space(lab):
    """The detail route carries only the schedule pk, so it must resolve the machine.

    PATCH-only by design, so this is also the edit path: a laser manager must not be able
    to rewrite the printer team's service interval.
    """
    schedule = MaintenanceSchedule.objects.create(
        machine=lab["printer"],
        description="Printer belt",
        interval_days=30,
        next_due=timezone.localdate(),
    )

    response = client_for(lab["laser_mgr"]).patch(
        reverse("admin-maintenance-schedule-detail", args=[schedule.pk]),
        {"interval_days": 999},
        format="json",
    )

    assert response.status_code in DENIED
    schedule.refresh_from_db()
    assert schedule.interval_days == 30


def test_maintenance_logs_are_scoped_to_the_team_s_machines(lab):
    laser_client = client_for(lab["laser_mgr"])

    other = laser_client.get(
        reverse(
            "admin-maintenance-log-list-create",
            args=[lab["space"].pk, lab["printer"].pk],
        )
    )
    own = laser_client.get(
        reverse(
            "admin-maintenance-log-list-create",
            args=[lab["space"].pk, lab["laser"].pk],
        )
    )

    assert other.status_code in DENIED
    assert own.status_code not in DENIED


def test_a_space_manager_reaches_both_machines_across_every_read_surface(lab):
    """The exemption must survive the sweep, or scoping has broken administration."""
    manager = User.objects.create_user(
        username="sweep-space-manager",
        email="sweep-sm@e.com",
        access_status=User.AccessStatus.ACTIVE,
    )
    MakerspaceMembership.objects.create(
        user=manager,
        makerspace=lab["space"],
        role=MakerspaceMembership.Role.SPACE_MANAGER,
        assigned_role=MakerspaceRole.objects.get(
            makerspace=lab["space"], slug="space_manager"
        ),
    )
    client = client_for(manager)

    for route in MACHINE_PK_READS:
        for machine in (lab["printer"], lab["laser"]):
            response = client.get(reverse(route, args=[machine.pk]))
            assert response.status_code not in DENIED, (
                f"{route} denied a space manager machine {machine.pk}"
            )


def test_a_role_with_the_grant_and_no_links_reaches_no_machine_read_surface(lab):
    """Fail-closed, end to end: the grant alone must not open any per-machine surface."""
    unlinked = User.objects.create_user(
        username="sweep-unlinked",
        email="sweep-unlinked@e.com",
        role=User.Role.REQUESTER,
        access_status=User.AccessStatus.ACTIVE,
    )
    role = MakerspaceRole.objects.create(
        makerspace=lab["space"],
        name="Unlinked",
        slug="sweep-unlinked",
        granted_actions=[Action.MANAGE_MACHINES],
    )
    MakerspaceMembership.objects.create(
        user=unlinked,
        makerspace=lab["space"],
        role=MakerspaceMembership.Role.CUSTOM,
        assigned_role=role,
    )
    client = client_for(unlinked)

    for route in MACHINE_PK_READS:
        for machine in (lab["printer"], lab["laser"]):
            response = client.get(reverse(route, args=[machine.pk]))
            assert response.status_code in DENIED, (
                f"{route} was reachable by a role holding no machine links"
            )
