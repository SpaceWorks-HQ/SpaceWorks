"""apps/devices under the tombstone profile (forward plan phase 7a).

Surfaces gone -- staff admin, the signed device protocol, Django admin, OpenAPI -- while
the models, the migrations and the retention registry (purge plan) stay present.
"""

import pytest
from django.contrib import admin
from django.urls import Resolver404, resolve
from rest_framework.test import APIClient

from apps.devices.models import Device, DeviceEnrollment, DeviceEvent
from apps.makerspaces.module_purge_plans import BY_KEY as PURGE_PLANS
from apps.makerspaces.module_registry import module_available
from apps.separability.registry import runtime_active

pytestmark = pytest.mark.django_db


def test_the_app_is_registered_as_inactive():
    assert runtime_active("devices") is False
    assert module_available("devices") is False


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/admin/makerspace/1/devices",
        "/api/v1/admin/devices/00000000-0000-4000-8000-000000000001",
        "/api/v1/device/enrollments/00000000-0000-4000-8000-000000000001/challenge",
        "/api/v1/device/heartbeat",
    ],
)
def test_no_device_route_resolves(path):
    with pytest.raises(Resolver404):
        resolve(path)


def test_device_endpoints_return_404():
    assert APIClient().post("/api/v1/device/heartbeat").status_code == 404


def test_the_admin_does_not_register_the_models():
    for model in (Device, DeviceEnrollment, DeviceEvent):
        assert model not in admin.site._registry


def test_the_openapi_schema_does_not_advertise_devices():
    response = APIClient().get("/schema/?format=json")
    assert response.status_code == 200
    assert b"/api/v1/device/" not in response.content
    assert b"/api/v1/admin/devices/" not in response.content


def test_retention_survives_the_tombstone():
    assert "devices" in PURGE_PLANS
    assert Device.objects.count() == 0  # the table is still installed and queryable
