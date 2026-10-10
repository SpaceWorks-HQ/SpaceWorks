import pytest
from django.contrib import admin
from django.urls import Resolver404, resolve
from rest_framework.test import APIClient

from apps.devices.models import LabelPrintCommand, LabelPrintResult

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("path", [
    "/api/v1/admin/qr-print-batches/1/label-commands",
    "/api/v1/device/label-commands/00000000-0000-4000-8000-000000000001/content",
    "/api/v1/device/label-commands/00000000-0000-4000-8000-000000000001/result",
])
def test_label_routes_are_absent_when_devices_are_tombstoned(path):
    with pytest.raises(Resolver404):
        resolve(path)
    assert APIClient().get(path).status_code == 404


def test_label_schema_and_admin_are_absent_but_history_tables_remain():
    for model in [LabelPrintCommand, LabelPrintResult]:
        assert model not in admin.site._registry
        assert model.objects.count() == 0
    response = APIClient().get("/schema/?format=json")
    assert response.status_code == 200
    assert b"/label-commands/" not in response.content
