"""Printer runtime surfaces disappear; the retained models stay installed."""
import pytest
from django.contrib import admin
from django.urls import Resolver404, resolve
from rest_framework.test import APIClient

from apps.devices.models import DeviceCommand, PrinterDeviceBinding, PrinterJob, PrinterJobConsumption

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("path", [
    "/api/v1/admin/makerspace/1/device-printer-bindings",
    "/api/v1/admin/makerspace/1/printer-jobs",
    "/api/v1/admin/device-printer-bindings/00000000-0000-4000-8000-000000000001",
    "/api/v1/admin/printer-jobs/00000000-0000-4000-8000-000000000001",
    "/api/v1/admin/printer-jobs/00000000-0000-4000-8000-000000000001/apply",
    "/api/v1/device/commands/lease",
    "/api/v1/device/commands/00000000-0000-4000-8000-000000000001/ack",
    "/api/v1/device/printer-jobs/00000000-0000-4000-8000-000000000001/telemetry",
    "/api/v1/device/printer-jobs/00000000-0000-4000-8000-000000000001/result",
])
def test_printer_routes_are_absent_when_devices_are_tombstoned(path):
    with pytest.raises(Resolver404):
        resolve(path)
    assert APIClient().post(path, {}, format="json").status_code == 404


def test_printer_admin_and_schema_are_absent_but_tables_remain():
    for model in (DeviceCommand, PrinterDeviceBinding, PrinterJob, PrinterJobConsumption):
        assert model not in admin.site._registry
        assert model.objects.count() == 0
    schema = APIClient().get("/schema/?format=json")
    assert schema.status_code == 200
    assert b"/printer-jobs" not in schema.content and b"/device-printer-bindings" not in schema.content
