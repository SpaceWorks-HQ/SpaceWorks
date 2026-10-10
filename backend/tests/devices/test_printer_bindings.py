import pytest
from django.urls import reverse
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.accounts.models import User
from apps.devices.models import Device, DeviceCommand, PrinterDeviceBinding, PrinterJob
from apps.devices.services_printer_bindings import create_binding, delete_binding, update_binding
from apps.machines.models import RoleMachineScope
from apps.makerspaces.models import MakerspaceMembership, MakerspaceRole
from tests.devices.printer_helpers import printer_case
from tests.return_helpers import make_member

pytestmark = pytest.mark.django_db


def test_bindings_default_to_manual_review_and_reject_cross_tenant_wrong_kind():
    case = printer_case("printer-binding")
    assert case["binding"].auto_apply_terminal is False
    other = printer_case("printer-binding-other")
    with pytest.raises(ValidationError):
        create_binding(case["actor"], case["space"].pk, device_id=other["device"].pk, machine_id=case["machine"].pk)
    Device.objects.filter(pk=case["device"].pk).update(kind="generic")
    delete_binding(case["actor"], case["binding"].pk)
    with pytest.raises(ValidationError):
        create_binding(case["actor"], case["space"].pk, device_id=case["device"].pk, machine_id=case["machine"].pk)


def test_manage_devices_alone_never_widens_machine_scope():
    case = printer_case("printer-scoped-binding")
    actor = make_member("printer-scoped-user", case["space"], membership_role="custom", role=User.Role.REQUESTER)
    role = MakerspaceRole.objects.create(makerspace=case["space"], slug="printer-scoped", name="Printer scoped",
                                        granted_actions=["manage_devices", "manage_machines"])
    membership = MakerspaceMembership.objects.get(user=actor, makerspace=case["space"])
    membership.assigned_role = role
    membership.save(update_fields=["assigned_role"])
    case["client"].force_authenticate(actor)
    listed = case["client"].get(reverse("devices:admin-printer-binding-list", args=[case["space"].pk]))
    assert listed.status_code == 200 and listed.data["results"] == []
    assert case["client"].patch(reverse("devices:admin-printer-binding-detail", args=[case["binding"].pk]), {"enabled": False}, format="json").status_code == 404
    RoleMachineScope.objects.create(role=role, machine=case["machine"])
    listed = case["client"].get(reverse("devices:admin-printer-binding-list", args=[case["space"].pk]))
    assert len(listed.data["results"]) == 1
    assert case["client"].patch(reverse("devices:admin-printer-binding-detail", args=[case["binding"].pk]), {"auto_apply_terminal": True}, format="json").status_code == 200


def test_disabling_or_deleting_binding_cancels_acknowledged_work_and_preserves_history():
    case = printer_case("printer-unbind", leased=True)
    update_binding(case["actor"], case["binding"].pk, {"enabled": False})
    assert DeviceCommand.objects.get(pk=case["job"].command_id).status == "cancelled"
    assert PrinterJob.objects.get(pk=case["job"].pk).state == "cancelled"
    delete_binding(case["actor"], case["binding"].pk)
    assert not PrinterDeviceBinding.objects.filter(pk=case["binding"].pk).exists()
    assert PrinterJob.objects.filter(pk=case["job"].pk).exists()


def test_binding_service_denies_missing_device_authority():
    case = printer_case("printer-no-device-role")
    actor = make_member("printer-machine-manager", case["space"], membership_role="machine_manager", role=User.Role.REQUESTER)
    with pytest.raises(PermissionDenied):
        create_binding(actor, case["space"].pk, device_id=case["device"].pk, machine_id=case["machine"].pk)


def test_explicit_unbind_retires_inert_imported_review_without_workflow_effect():
    case = printer_case("printer-import-review-unbind")
    DeviceCommand.objects.filter(pk=case["job"].command_id).update(status="cancelled")
    PrinterJob.objects.filter(pk=case["job"].pk).update(state="needs_review")
    delete_binding(case["actor"], case["binding"].pk)
    assert PrinterJob.objects.get(pk=case["job"].pk).state == "cancelled"
    case["request"].refresh_from_db()
    assert case["request"].status == "in_progress"
