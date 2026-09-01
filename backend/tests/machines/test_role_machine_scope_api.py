"""The staff console surface for editing a role's machine scope.

Console parity: machine scoping fails closed, so without this endpoint a Space Manager
could create a machine-managing role and have no way to make it able to manage anything.
"""

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.accounts.rbac import Action
from apps.audit.models import AuditLog
from apps.machines.models import Machine, MachineType, RoleMachineTypeScope
from apps.makerspaces.models import Makerspace, MakerspaceMembership, MakerspaceRole

pytestmark = pytest.mark.django_db


@pytest.fixture
def lab():
    space = Makerspace.objects.create(name="scope-api", slug="scope-api")
    printers = MachineType.objects.create(slug="api-printer", name="Printer", makerspace=space)
    lasers = MachineType.objects.create(slug="api-laser", name="Laser", makerspace=space)
    printer = Machine.objects.create(makerspace=space, machine_type=printers, name="Prusa")
    boss = User.objects.create_user(
        username="scope-api-boss",
        email="scope-api-boss@e.com",
        role=User.Role.REQUESTER,
        access_status=User.AccessStatus.ACTIVE,
    )
    MakerspaceMembership.objects.create(
        user=boss, makerspace=space, role=MakerspaceMembership.Role.SPACE_MANAGER
    )
    team = MakerspaceRole.objects.create(
        makerspace=space,
        name="Laser Team",
        slug="laser-team",
        granted_actions=[Action.MANAGE_MACHINES],
    )
    return {
        "space": space,
        "printers": printers,
        "lasers": lasers,
        "printer": printer,
        "boss": boss,
        "team": team,
    }


def client_for(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def scope_url(lab, role=None):
    return reverse(
        "admin-role-machine-scope",
        args=[lab["space"].id, (role or lab["team"]).pk],
    )


def test_the_editor_returns_current_links_and_every_option(lab):
    RoleMachineTypeScope.objects.create(role=lab["team"], machine_type=lab["lasers"])

    body = client_for(lab["boss"]).get(scope_url(lab)).json()

    assert body["machine_type_ids"] == [lab["lasers"].pk]
    assert body["machine_ids"] == []
    offered = {row["id"] for row in body["available_machine_types"]}
    assert {lab["printers"].pk, lab["lasers"].pk} <= offered
    assert body["scoping_applies"] is True


def test_saving_replaces_the_selection_so_unticking_works(lab):
    RoleMachineTypeScope.objects.create(role=lab["team"], machine_type=lab["lasers"])

    body = client_for(lab["boss"]).put(
        scope_url(lab),
        {"machine_type_ids": [lab["printers"].pk], "machine_ids": [lab["printer"].pk]},
        format="json",
    ).json()

    assert body["machine_type_ids"] == [lab["printers"].pk]
    assert body["machine_ids"] == [lab["printer"].pk]
    assert RoleMachineTypeScope.objects.filter(
        role=lab["team"], machine_type=lab["lasers"]
    ).exists() is False


def test_clearing_the_selection_is_allowed_and_fails_closed(lab):
    RoleMachineTypeScope.objects.create(role=lab["team"], machine_type=lab["lasers"])

    body = client_for(lab["boss"]).put(
        scope_url(lab), {"machine_type_ids": [], "machine_ids": []}, format="json"
    ).json()

    assert body["machine_type_ids"] == []
    assert body["machine_ids"] == []


def test_another_makerspace_s_machine_is_rejected_not_silently_dropped(lab):
    # A save that quietly discards half the selection leaves the administrator believing
    # a team has access it does not have.
    other = Makerspace.objects.create(name="scope-api-other", slug="scope-api-other")
    other_type = MachineType.objects.create(
        slug="api-other-type", name="Other", makerspace=other
    )

    response = client_for(lab["boss"]).put(
        scope_url(lab),
        {"machine_type_ids": [other_type.pk], "machine_ids": []},
        format="json",
    )

    assert response.status_code == 400
    assert RoleMachineTypeScope.objects.filter(role=lab["team"]).exists() is False


def test_a_scope_change_is_audited(lab):
    client_for(lab["boss"]).put(
        scope_url(lab),
        {"machine_type_ids": [lab["printers"].pk], "machine_ids": []},
        format="json",
    )

    assert AuditLog.objects.filter(action="role.machine_scope_changed").exists()


def test_an_exempt_role_reports_that_scoping_does_not_apply(lab):
    # The console must render the editor inert rather than let someone tick boxes that
    # `role_scope` will ignore for a MANAGE_MAKERSPACE holder.
    boss_role = MakerspaceRole.objects.get(
        makerspace=lab["space"], slug="space_manager"
    )

    body = client_for(lab["boss"]).get(scope_url(lab, boss_role)).json()

    assert body["scoping_applies"] is False


def test_a_role_granting_no_machine_authority_reports_no_scoping(lab):
    front_desk = MakerspaceRole.objects.create(
        makerspace=lab["space"],
        name="Front Desk",
        slug="front-desk",
        granted_actions=[Action.VIEW_INVENTORY],
    )

    body = client_for(lab["boss"]).get(scope_url(lab, front_desk)).json()

    assert body["scoping_applies"] is False


def test_a_non_manager_cannot_read_or_edit_scope(lab):
    outsider = User.objects.create_user(
        username="scope-api-outsider",
        email="scope-api-outsider@e.com",
        role=User.Role.REQUESTER,
        access_status=User.AccessStatus.ACTIVE,
    )
    MakerspaceMembership.objects.create(
        user=outsider,
        makerspace=lab["space"],
        role=MakerspaceMembership.Role.CUSTOM,
        assigned_role=lab["team"],
    )

    assert client_for(outsider).get(scope_url(lab)).status_code == 403
    assert client_for(outsider).put(
        scope_url(lab), {"machine_type_ids": [], "machine_ids": []}, format="json"
    ).status_code == 403
