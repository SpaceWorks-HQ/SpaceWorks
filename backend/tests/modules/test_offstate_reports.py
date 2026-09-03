"""OFF-state contracts for module-owned reporting data."""

from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.inventory.models import InventoryAsset, InventoryProduct
from apps.machines.models import Machine, MachineServiceRequest, MachineType, ServiceQueue
from apps.makerspaces.models import Makerspace
from apps.operations.report_registry import report_definition


pytestmark = pytest.mark.django_db


def _space(slug, *, without):
    space = Makerspace.objects.create(name=slug, slug=slug)
    space.enabled_modules.remove(without)
    space.save(update_fields=["enabled_modules"])
    return space


def _enable(space, module_key):
    space.enabled_modules = sorted({*(space.enabled_modules or []), module_key})
    space.save(update_fields=["enabled_modules"])


def _superadmin_client(slug):
    user = User.objects.create_user(
        username=slug,
        email=f"{slug}@example.test",
        role=User.Role.SUPERADMIN,
        is_staff=True,
        is_superuser=True,
        access_status=User.AccessStatus.ACTIVE,
    )
    client = APIClient()
    client.force_authenticate(user)
    return client


def _completed_print(space):
    printer_type = MachineType.objects.get(makerspace__isnull=True, slug="3d_printer")
    machine = Machine.objects.create(
        makerspace=space,
        machine_type=printer_type,
        name="Retained printer",
        type_payload={"model": "MK4"},
    )
    queue = ServiceQueue.objects.create(
        makerspace=space,
        machine_type=printer_type,
        name="Retained print queue",
    )
    requester = User.objects.create_user(
        username="offstate-printer-requester",
        email="offstate-printer-requester@example.test",
    )
    MachineServiceRequest.objects.create(
        makerspace=space,
        queue=queue,
        requester=requester,
        requester_name=requester.username,
        assigned_machine=machine,
        title="Retained print job",
        status=MachineServiceRequest.Status.COMPLETED,
        actual_minutes=60,
        actual_consumed_grams=Decimal("10.00"),
        completed_at=timezone.now(),
        run_machine_model="MK4",
    )
    return machine


def test_printing_off_hides_printer_reports_and_on_restores_them():
    space = _space("reports-printing-gate", without="printing")
    assert "machine_service" in space.enabled_modules
    machine = _completed_print(space)
    client = _superadmin_client("reports-printing-superadmin")
    export_url = reverse(
        "report-export",
        kwargs={"makerspace_id": space.id, "report_key": "printer-service"},
    )
    makerspace_url = reverse("admin-makerspace-machine-service-report", args=[space.id])
    aggregate_url = reverse("admin-machine-service-report")

    assert report_definition("printer-service").required_modules == ("printing",)
    refused_definition = client.get(export_url, {"format": "csv"})
    refused_branch = client.get(makerspace_url, {"machine_type": "3d_printer"})
    aggregate_off = client.get(aggregate_url, {"machine_type": "3d_printer"})

    assert refused_definition.status_code == 400
    assert "printing" in str(refused_definition.data)
    assert refused_branch.status_code == 400
    assert "printing" in str(refused_branch.data)
    assert aggregate_off.status_code == 200, aggregate_off.data
    assert aggregate_off.data["printer_metrics"] == []

    _enable(space, "printing")
    enabled_definition = client.get(export_url, {"format": "csv"})
    enabled_branch = client.get(makerspace_url, {"machine_type": "3d_printer"})
    aggregate_on = client.get(aggregate_url, {"machine_type": "3d_printer"})

    assert enabled_definition.status_code == 200
    assert enabled_branch.status_code == 200, enabled_branch.data
    assert [row["machine_id"] for row in enabled_branch.data["printer_metrics"]] == [machine.id]
    assert aggregate_on.status_code == 200, aggregate_on.data
    assert [row["machine_id"] for row in aggregate_on.data["printer_metrics"]] == [machine.id]


def test_membership_off_hides_member_activity_and_on_restores_it():
    space = _space("reports-membership-gate", without="membership")
    client = _superadmin_client("reports-membership-superadmin")
    makerspace_url = reverse("analytics-member-activity", args=[space.id])
    aggregate_url = reverse("analytics-aggregate", args=["member-activity"])

    assert report_definition("member-activity").required_modules == ("membership",)
    refused = client.get(makerspace_url)
    aggregate_off = client.get(aggregate_url)

    assert refused.status_code == 400
    assert "membership" in str(refused.data)
    assert aggregate_off.status_code == 200, aggregate_off.data
    assert aggregate_off.data["typed_rows"] == []

    _enable(space, "membership")
    enabled = client.get(makerspace_url)
    aggregate_on = client.get(aggregate_url)

    assert enabled.status_code == 200, enabled.data
    assert enabled.data["typed_rows"][0]["makerspace_name"] == space.name
    assert aggregate_on.status_code == 200, aggregate_on.data
    assert [row["makerspace_id"] for row in aggregate_on.data["typed_rows"]] == [space.id]


def test_asset_units_off_hides_retained_assets_and_on_restores_them():
    space = _space("reports-asset-units-gate", without="asset_units")
    product = InventoryProduct.objects.create(
        makerspace=space,
        name="Retained drill",
        total_quantity=0,
        available_quantity=0,
    )
    InventoryAsset.objects.create(
        makerspace=space,
        product=product,
        asset_tag="RETAINED-1",
    )
    client = _superadmin_client("reports-asset-units-superadmin")
    makerspace_url = reverse("analytics-summary", args=[space.id])
    aggregate_url = reverse("analytics-aggregate", args=["summary"])

    hidden = client.get(makerspace_url)
    aggregate_off = client.get(aggregate_url)

    assert hidden.status_code == 200, hidden.data
    assert hidden.data["assets"] == 0
    assert aggregate_off.status_code == 200, aggregate_off.data
    assert aggregate_off.data["assets"] == 0

    _enable(space, "asset_units")
    visible = client.get(makerspace_url)
    aggregate_on = client.get(aggregate_url)

    assert visible.status_code == 200, visible.data
    assert visible.data["assets"] == 1
    assert aggregate_on.status_code == 200, aggregate_on.data
    assert aggregate_on.data["assets"] == 1
