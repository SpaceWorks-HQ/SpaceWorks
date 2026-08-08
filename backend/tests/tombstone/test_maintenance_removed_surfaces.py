"""apps/maintenance under the tombstone profile (plan B5/B6, phase 11).

Maintenance has its own module key, so the console needs nothing new -- the key is
dropped from `enabled_modules` and the tab goes with it. What this phase adds is the
`admin_api` relocation, and the assertion that matters most is the negative one:
maintenance routes hang off `makerspaces/<id>/machines/<id>/...`, sharing a prefix with
routes that stayed in `admin_api`, so withdrawing them must not disturb the neighbours.
"""

import pytest
from django.contrib import admin
from django.urls import Resolver404, resolve
from django.utils import timezone
from rest_framework.test import APIClient

from apps.maintenance.models import MaintenanceLog, MaintenanceLogDocument, MaintenanceSchedule
from apps.makerspaces.models import Makerspace
from apps.makerspaces.module_registry import module_available
from apps.makerspaces.platform import available_modules
from apps.separability.registry import purge_plan_for, runtime_active

pytestmark = pytest.mark.django_db


# --------------------------------------------------------------------------
# Surfaces: gone.
# --------------------------------------------------------------------------

def test_the_app_is_registered_as_inactive():
    assert runtime_active("maintenance") is False
    assert module_available("maintenance") is False


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/admin/makerspaces/1/machines/1/maintenance/schedules/",
        "/api/v1/admin/makerspaces/1/machines/1/maintenance/logs/",
        "/api/v1/admin/maintenance/schedules/1/",
        "/api/v1/admin/maintenance/schedules/1/deactivate/",
        "/api/v1/admin/maintenance/logs/1/documents/",
        "/api/v1/admin/maintenance/logs/1/documents/presign/",
        "/api/v1/admin/maintenance/log-documents/1/",
        "/api/v1/admin/maintenance/log-documents/1/url/",
    ],
)
def test_no_maintenance_route_resolves(path):
    with pytest.raises(Resolver404):
        resolve(path)


def test_the_machine_routes_that_stayed_in_admin_api_still_resolve():
    """Maintenance shared the machines/ prefix; withdrawing it must not take neighbours."""
    assert resolve("/api/v1/admin/machines/1/publicity").url_name == "admin-machine-publicity"
    assert resolve("/api/v1/admin/makerspaces/1/roles/1").url_name == "admin-role-detail"
    assert resolve("/api/v1/admin/makerspaces/1/spaces/").url_name == "admin-bookable-space-list-create"


def test_the_admin_does_not_register_the_models():
    for model in (MaintenanceSchedule, MaintenanceLog, MaintenanceLogDocument):
        assert model not in admin.site._registry


def test_the_openapi_schema_does_not_advertise_maintenance():
    response = APIClient().get("/schema/?format=json")

    assert response.status_code == 200
    assert b"/maintenance/" not in response.content


def test_the_module_is_not_offered_to_the_console():
    space = Makerspace.objects.create(name="tombstoned-maint", slug="tombstoned-maint")
    space.enabled_modules = sorted(set(space.enabled_modules) | {"maintenance"})
    space.save(update_fields=["enabled_modules"])

    assert "maintenance" not in available_modules(space)


# --------------------------------------------------------------------------
# Data and retention: untouched.
# --------------------------------------------------------------------------

def test_schedule_rows_are_still_readable():
    from tests.return_helpers import make_space
    from apps.machines.models import Machine, MachineType

    space = make_space("retained-maintenance")
    machine = Machine.objects.create(
        makerspace=space,
        machine_type=MachineType.objects.get(makerspace__isnull=True, slug="3d_printer"),
        name="P1",
    )
    schedule = MaintenanceSchedule.objects.create(
        machine=machine,
        description="Lubricate rails",
        interval_days=30,
        next_due=timezone.localdate(),
    )

    assert MaintenanceSchedule.objects.get(pk=schedule.pk).description == "Lubricate rails"


def test_the_purge_plan_is_still_registered():
    """Log documents live in the private bucket; the plan is what names their keys."""
    plan = purge_plan_for("maintenance")

    assert plan is not None
    assert plan.private_keys is not None
