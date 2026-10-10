import pytest
from uuid import uuid4

from apps.devices.models import Device, DeviceCommand, PrinterDeviceBinding, PrinterJob, PrinterJobConsumption
from apps.devices.services_commands import acknowledge, lease_command
from apps.devices.services_identity import create_device
from apps.devices.services_printer_bindings import create_binding
from apps.devices.services_printer_jobs import create_job
from apps.devices.services_printer_apply import report_result
from apps.devices.principal import DevicePrincipal
from apps.makerspaces.models import MakerspaceMembership
from apps.tenant_migration.materialization import materialize_tenant
from apps.tenant_migration.projection_guards import validate_projection_registry
from apps.tenant_migration.reference_guards import validate_reference_registry
from apps.tenant_migration.tenant_dump_catalog import validate_catalog
from apps.tenant_migration.target_projection import TARGET_FIELD_PROJECTION
from apps.tenant_migration.row_planning import _apply_target_fields
from tests.data_export.portable_helpers import make_space, make_user
from tests.devices.helpers import enroll
from tests.encryption.conftest import enabled_encryption
from tests.tenant_migration.materialization_helpers import portable_import_case
from tests.test_machine_service_workflow import machine
from apps.machines import role_scope, service_workflow as workflow
from apps.machines.models import MachineConsumable

pytestmark = pytest.mark.django_db(transaction=True)


def test_printer_catalog_projection_references_and_uniqueness_are_complete():
    validate_catalog()
    validate_projection_registry()
    validate_reference_registry()


@pytest.mark.parametrize("state,expected", [("awaiting", "needs_review"), ("reported", "needs_review"), ("needs_review", "needs_review"), ("applied", "applied"), ("cancelled", "cancelled")])
def test_conditional_field_projection_inerts_unprocessed_work_and_preserves_history(state, expected):
    row = {"state": state}
    _apply_target_fields("devices.PrinterJob", {"state": state}, row)
    assert row["state"] == expected
    assert TARGET_FIELD_PROJECTION[("devices.PrinterDeviceBinding", "enabled")].value is False


def _prepare(space, user, _request):
    membership = MakerspaceMembership.objects.get(makerspace=space, user=user)
    membership.assigned_role = space.roles.get(slug="space_manager")
    membership.save(update_fields=["assigned_role"])
    device, grant, token = create_device(user, space.pk, kind="printer", name="Moved printer")
    response, _private, _public = enroll({"enrollment_id": grant.pk, "token": token})
    assert response.status_code == 200
    device.refresh_from_db()
    target = machine(space)
    request = workflow.submit(target, user, actor=user, requester_name="Member",
        contact_email=user.email, contact_phone="123", title="Moved job")
    workflow.accept(request, user)
    request = workflow.start(request, user, role_scope.EXEMPT, machine_id=target.pk)
    binding = create_binding(user, space.pk, device_id=device.pk, machine_id=target.pk, auto_apply_terminal=True)
    job = create_job(user, space.pk, binding_id=binding.pk, service_request_id=request.pk, external_job_id="source-print")
    principal = DevicePrincipal.from_device(device)
    lease = lease_command(principal)
    acknowledge(principal, job.command_id, lease["lease_token"])
    stock = MachineConsumable.objects.create(machine=target, measurement="grams", label="Moved material", remaining=100)
    report_result(principal, job.pk, {"operation_id": str(uuid4()), "external_job_id": job.external_job_id,
        "outcome": "failed", "actual_minutes": 2, "consumptions": [{"machine_consumable_id": stock.pk, "quantity": "2"}],
        "failure_reason": "Fault", "percent_complete": 20})
    pending_request = workflow.submit(target, user, actor=user, requester_name="Member",
        contact_email=user.email, contact_phone="123", title="Pending moved job")
    workflow.accept(pending_request, user)
    pending_request = workflow.start(pending_request, user, role_scope.EXEMPT, machine_id=target.pk)
    pending_job = create_job(user, space.pk, binding_id=binding.pk, service_request_id=pending_request.pk, external_job_id="source-pending")
    return {"job": job, "machine": target, "device": device, "request": request, "stock": stock, "pending_job": pending_job}


def test_portable_printer_history_imports_with_no_remote_authority_and_no_workflow_replay():
    with enabled_encryption():
        user, source = make_user("printer-move"), make_space("printer-move")
        source.enabled_modules = sorted(set(source.enabled_modules) | {"devices", "machines", "machine_service"})
        source.save(update_fields=["enabled_modules"])
        with portable_import_case(source, user, prepare_source=_prepare) as case:
            case.decide_walk_in(user)
            graph = case.source_data
            result = materialize_tenant(case.root, case.job, case.carried,
                target_identity={"name": "Moved printers", "slug": "moved-printers"}, batch_size=2)
        # Reads stay inside enabled_encryption(): the PII mapper needs the key context.
        binding = PrinterDeviceBinding.objects.get(makerspace_id=result.target_makerspace_id)
        jobs = PrinterJob.objects.filter(makerspace_id=result.target_makerspace_id)
        job = jobs.get(external_job_id="source-print")
        command = job.command
        assert not binding.enabled and not binding.auto_apply_terminal
        assert command.status == "cancelled" and command.lease_token_digest is None and command.lease_expires_at is None
        assert job.pk != graph["job"].pk and job.state == "applied" and job.failure_reason == "Fault"
        assert job.machine_id != graph["machine"].pk and job.machine_id_snapshot == graph["machine"].pk
        assert job.service_request_id != graph["request"].pk and job.service_request_id_snapshot == graph["request"].pk
        assert Device.objects.get(pk=job.device_id).status == "pending"
        assert all(row.status == "cancelled" and row.lease_token_digest is None and row.lease_expires_at is None
                   for row in DeviceCommand.objects.filter(makerspace_id=result.target_makerspace_id))
        pending = jobs.get(external_job_id="source-pending")
        assert pending.state == "needs_review" and pending.reported_at is None
        consumption = PrinterJobConsumption.objects.get(job=job)
        assert consumption.machine_consumable_id != graph["stock"].pk
        assert consumption.machine_consumable_id_snapshot == graph["stock"].pk and consumption.quantity == 2
        assert consumption.machine_consumable.remaining == 98
        from apps.audit.models import AuditLog
        # Exactly one source outcome travels; import never invokes the adapter/workflow again.
        assert AuditLog.objects.filter(makerspace_id=result.target_makerspace_id, action="devices.printer_result_applied").count() == 1
        assert AuditLog.objects.get(makerspace_id=result.target_makerspace_id, action="devices.printer_result_claimed").meta["printer_job_id"] == str(job.pk)
