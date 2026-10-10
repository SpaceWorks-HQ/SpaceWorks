from uuid import uuid4

import pytest

from apps.audit.models import AuditLog
from apps.devices.models import Device, LabelPrintCommand, LabelPrintResult
from apps.devices.models_commands import DeviceCommand
from apps.devices.principal import DevicePrincipal
from apps.devices.services_commands import acknowledge, lease_command
from apps.devices.services_identity import create_device
from apps.devices.services_label_commands import create_label_command
from apps.devices.services_label_results import report_result
from apps.makerspaces.models import MakerspaceMembership
from apps.tenant_migration.materialization import materialize_tenant
from apps.tenant_migration.projection_guards import validate_projection_registry
from apps.tenant_migration.reference_guards import validate_reference_registry
from apps.tenant_migration.row_planning import _apply_target_fields
from apps.tenant_migration.tenant_dump_catalog import validate_catalog
from tests.data_export.portable_helpers import make_space, make_user
from tests.devices.helpers import enroll
from tests.devices.helpers_labels import batch_fixture
from tests.encryption.conftest import enabled_encryption
from tests.tenant_migration.materialization_helpers import portable_import_case

pytestmark = pytest.mark.django_db(transaction=True)


def test_label_tenant_catalog_projection_references_and_unique_rules_are_complete():
    # Includes the combined 7b+7c model graph and independent literal snapshots.
    validate_catalog()
    validate_projection_registry()
    validate_reference_registry()


@pytest.mark.parametrize("status", ["queued", "leased", "acknowledged", "delivery_failed", "cancelled"])
def test_every_imported_command_is_cancelled_and_lease_ownership_cleared(status):
    source = {"status": status, "lease_token_digest": "digest", "lease_expires_at": "date",
              "acknowledged_at": "date"}
    row = dict(source)
    _apply_target_fields("devices.DeviceCommand", source, row)
    assert row == {"status": "cancelled", "lease_token_digest": None,
                   "lease_expires_at": None, "acknowledged_at": None}


def prepare_labels(space, user, _request):
    space.enabled_modules = sorted(set(space.enabled_modules) | {"devices", "qr_print_batches"})
    space.save(update_fields=["enabled_modules"])
    membership = MakerspaceMembership.objects.get(makerspace=space, user=user)
    membership.assigned_role = space.roles.get(slug="space_manager")
    membership.save(update_fields=["assigned_role"])
    device, grant, token = create_device(user, space.pk, kind="label_printer", name="Moved label printer")
    response, _private, _public = enroll({"enrollment_id": grant.pk, "token": token})
    assert response.status_code == 200
    device.refresh_from_db()
    batch = batch_fixture(space, user)
    principal = DevicePrincipal.from_device(device)
    labels, receipt = [], None
    for outcome in ["succeeded", "retryable_failed", "pending"]:
        label, _created = create_label_command(user, batch.pk, device_id=device.pk, request_id=uuid4())
        labels.append(label)
        if outcome == "pending":
            continue
        leased = lease_command(principal)
        assert leased["label_command_id"] == label.pk
        acknowledge(principal, label.command_id, leased["lease_token"])
        receipt = report_result(principal, label.pk, operation_id=uuid4(), outcome=outcome,
                                result_code="ok" if outcome == "succeeded" else "offline")
    return {"labels": labels, "device": device, "batch": batch, "receipt": receipt}


def test_portable_label_history_remaps_live_edges_preserves_receipts_and_never_prints():
    with enabled_encryption():
        user, source = make_user("label-move"), make_space("label-move")
        with portable_import_case(source, user, prepare_source=prepare_labels) as case:
            case.decide_walk_in(user)
            graph = case.source_data
            imported = materialize_tenant(case.root, case.job, case.carried,
                target_identity={"name": "Moved labels", "slug": "moved-labels"}, batch_size=2)
    tenant_id = imported.target_makerspace_id
    labels = list(LabelPrintCommand.objects.filter(makerspace_id=tenant_id))
    assert sorted(label.result for label in labels) == ["pending", "retryable_failed", "succeeded"]
    assert all(label.pk not in {old.pk for old in graph["labels"]} for label in labels)
    assert all(label.batch_id != graph["batch"].pk and label.batch_id_snapshot == graph["batch"].pk for label in labels)
    assert all(label.device_id != graph["device"].pk for label in labels)
    commands = DeviceCommand.objects.filter(makerspace_id=tenant_id)
    assert commands.count() == 3
    assert all(command.status == "cancelled" and command.lease_token_digest is None
               and command.lease_expires_at is None and command.acknowledged_at is None for command in commands)
    receipt = LabelPrintResult.objects.get(makerspace_id=tenant_id, operation_id=graph["receipt"].operation_id)
    assert receipt.pk != graph["receipt"].pk and receipt.response_command_status == "queued"
    device = Device.objects.get(makerspace_id=tenant_id)
    assert device.status == "pending" and device.public_key is None
    audit = AuditLog.objects.filter(makerspace_id=tenant_id, action="devices.label_command_created").first()
    assert audit.meta["device_id"] == str(device.pk)
    assert LabelPrintCommand.objects.filter(pk=audit.meta["label_command_id"], makerspace_id=tenant_id).exists()
    assert DeviceCommand.objects.filter(pk=audit.meta["command_id"], makerspace_id=tenant_id).exists()
    assert str(audit.meta["qr_batch_id"]) != str(graph["batch"].pk)
    # Even explicit target enrollment/module activation cannot revive source work.
    from django.contrib.auth import get_user_model
    from rest_framework.exceptions import PermissionDenied
    from apps.devices.services_enrollment import start_enrollment
    from apps.devices.services_label_delivery import command_content
    from apps.makerspaces.models import Makerspace

    target = Makerspace.objects.get(pk=tenant_id)
    target.enabled_modules = sorted(set(target.enabled_modules) | {"devices", "qr_print_batches"})
    # Activate the imported tenant first (materialization leaves it IMPORTING, which is
    # correctly unservable): the claim is that even a LIVE target cannot revive source work.
    from apps.encryption.models import PiiMakerspaceWriteFence
    from apps.encryption.write_fence import reopen

    root = get_user_model().objects.create_superuser("label-target-root", "root@example.test", "secret")
    fence = PiiMakerspaceWriteFence.objects.filter(makerspace_id=tenant_id).first()
    if fence is not None and fence.operation_id:
        reopen(fence.operation_id, root.pk)  # what target activation does to the import fence
    target.lifecycle_state = Makerspace.LifecycleState.ACTIVE
    target.save(update_fields=["enabled_modules", "lifecycle_state"])
    grant, token = start_enrollment(root, device.pk)
    response, _private, _public = enroll({"enrollment_id": grant.pk, "token": token})
    assert response.status_code == 200
    device.refresh_from_db()
    principal = DevicePrincipal.from_device(device)
    assert lease_command(principal) is None
    pending = next(label for label in labels if label.result == "pending")
    with pytest.raises(PermissionDenied):
        command_content(principal, pending.pk)
    with pytest.raises(PermissionDenied):
        report_result(principal, receipt.label_command_id, operation_id=receipt.operation_id,
                      outcome=receipt.outcome, result_code=receipt.result_code)



def test_raw_dump_cancels_label_parent_but_preserves_terminal_receipt_history():
    from apps.tenant_migration.tenant_dump_raw import sanitize_record
    from tests.devices.helpers_labels import label_case
    from tests.devices.test_printer_dump_projection import raw_row

    case = label_case("label-raw-dump", acknowledged=True)
    receipt = report_result(case["principal"], case["label"].pk,
        operation_id=uuid4(), outcome="succeeded", result_code="ok")
    command = sanitize_record(DeviceCommand, raw_row(DeviceCommand, case["label"].command_id)).values
    assert command["status"] == "cancelled"
    assert command["lease_token_digest"] is None and command["lease_expires_at"] is None
    assert command["acknowledged_at"] is None
    label = sanitize_record(LabelPrintCommand, raw_row(LabelPrintCommand, case["label"].pk)).values
    result = sanitize_record(LabelPrintResult, raw_row(LabelPrintResult, receipt.pk)).values
    assert label["result"] == result["response_result"] == "succeeded"
    assert result["response_command_status"] == "acknowledged"
