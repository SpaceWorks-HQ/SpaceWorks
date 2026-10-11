from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.machines.models import RoleMachineScope
from apps.makerspaces.models import MakerspaceMembership, MakerspaceRole
from apps.maintenance.models import MaintenanceSchedule
from tests.maintenance.helpers import make_machine_setup
from tests.return_helpers import authenticated_client, make_user

pytestmark = pytest.mark.django_db


def schedule(machine, **overrides):
    data = dict(machine=machine, description="Calibrate", interval_days=1,
                next_due=timezone.localdate() - timedelta(days=1))
    data.update(overrides)
    return MaintenanceSchedule.objects.create(**data)


def test_overdue_drilldown_filters_active_and_strict_past_due_with_pagination():
    space, manager, machine, _ = make_machine_setup("ux-overdue")
    other, _, other_machine, _ = make_machine_setup("ux-overdue-other")
    first = schedule(machine)
    schedule(machine, is_active=False)
    schedule(machine, next_due=timezone.localdate())
    schedule(other_machine)
    client = authenticated_client(manager)
    response = client.get(reverse("admin-maintenance-overdue", args=[space.pk]))
    assert response.status_code == 200
    assert response.data["count"] == 1
    assert response.data["results"][0]["id"] == first.pk
    assert response.data["results"][0]["machine_id"] == machine.pk
    assert client.get(reverse("admin-maintenance-overdue", args=[other.pk])).status_code == 404


def test_overdue_drilldown_has_no_fallback_for_an_empty_custom_machine_scope():
    space, _, machine, _ = make_machine_setup("ux-overdue-scope")
    actor = make_user("ux-scoped-machines", access_status="active")
    role = MakerspaceRole.objects.create(makerspace=space, name="Scoped maintainer", slug="ux-scoped",
                                         granted_actions=["manage_machines"])
    MakerspaceMembership.objects.create(makerspace=space, user=actor, assigned_role=role, role="custom")
    row = schedule(machine)
    url = reverse("admin-maintenance-overdue", args=[space.pk])
    client = authenticated_client(actor)
    assert client.get(url).data["count"] == 0
    RoleMachineScope.objects.create(role=role, machine=machine)
    assert [item["id"] for item in client.get(url).data["results"]] == [row.pk]


def test_overdue_drilldown_answers_400_when_maintenance_module_is_off():
    space, manager, _, _ = make_machine_setup("ux-overdue-off")
    space.enabled_modules = [key for key in space.enabled_modules if key != "maintenance"]
    space.save(update_fields=["enabled_modules"])
    assert authenticated_client(manager).get(reverse("admin-maintenance-overdue", args=[space.pk])).status_code == 400


def test_overdue_drilldown_paginates_without_writing_and_refuses_suspended_actors():
    from apps.audit.models import AuditLog

    space, manager, machine, _ = make_machine_setup("ux-overdue-pages")
    wanted = [schedule(machine).pk for _ in range(25)]
    before = AuditLog.objects.count()
    url = reverse("admin-maintenance-overdue", args=[space.pk])
    client = authenticated_client(manager)
    first = client.get(url)
    second = client.get(url, {"page": 2})
    assert first.status_code == second.status_code == 200
    assert first.data["count"] == second.data["count"] == 25
    assert [row["id"] for row in first.data["results"]] == wanted[:24]
    assert [row["id"] for row in second.data["results"]] == wanted[24:]
    assert AuditLog.objects.count() == before
    manager.access_status = "suspended"
    manager.save(update_fields=["access_status"])
    assert client.get(url).status_code == 403
