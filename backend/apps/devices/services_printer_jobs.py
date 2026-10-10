"""Create a command only for an explicitly identified in-progress service request."""
from django.db import IntegrityError, transaction
from rest_framework.exceptions import NotFound, ValidationError

from apps.devices.errors_printers import PrinterConflict
from apps.devices.models import Device, DeviceCommand, PrinterDeviceBinding, PrinterJob
from apps.devices.printer_access import authorize_staff, lock_printer_tenant, scope_printers
from apps.devices.services_printer_events import record
from apps.machines.models import Machine, MachineServiceRequest


def create_job(actor, makerspace_id, *, binding_id, service_request_id, external_job_id):
    external_job_id = str(external_job_id).strip()
    if not external_job_id or len(external_job_id) > 120:
        raise ValidationError("An external job identifier of at most 120 characters is required.")
    identity = scope_printers(actor, PrinterDeviceBinding.objects.all()).filter(pk=binding_id, makerspace_id=makerspace_id).values("device_id").first()
    if identity is None:
        raise NotFound()
    try:
        with transaction.atomic():
            makerspace = lock_printer_tenant(makerspace_id)
            device = Device.objects.select_for_update().filter(pk=identity["device_id"], makerspace=makerspace).first()
            binding = PrinterDeviceBinding.objects.filter(pk=binding_id, makerspace=makerspace, device=device).first()
            if device is None or binding is None:
                raise NotFound()
            authorize_staff(actor, makerspace_id, binding.machine)
            request = MachineServiceRequest.objects.select_for_update().filter(pk=service_request_id, makerspace=makerspace).first()
            if (request is None or request.status != MachineServiceRequest.Status.IN_PROGRESS or
                request.assigned_machine_id is None or request.assigned_machine_id != binding.machine_id):
                raise ValidationError("An in-progress request assigned to this printer is required.")
            machine = Machine.objects.select_for_update().filter(pk=request.assigned_machine_id, makerspace=makerspace).first()
            if machine is None:
                raise ValidationError("Machine belongs to a different makerspace.")
            binding = PrinterDeviceBinding.objects.select_for_update().filter(pk=binding_id, makerspace=makerspace, device=device).first()
            if binding is None:
                raise NotFound()
            if (device.makerspace_id != makerspace.pk or device.kind != Device.Kind.PRINTER or device.status != "active" or
                not binding.enabled or binding.machine_id != machine.pk or not machine.is_active):
                raise ValidationError("Binding is not available.")
            authorize_staff(actor, makerspace_id, machine)
            command = DeviceCommand.objects.create(makerspace=makerspace, device=device,
                device_key_version=device.key_version, created_by=actor)
            job = PrinterJob.objects.create(command=command, makerspace=makerspace, device=device,
                machine=machine, service_request=request, machine_id_snapshot=machine.pk,
                machine_name=machine.name, service_request_id_snapshot=request.pk,
                service_request_name=f"Request {request.pk}", external_job_id=external_job_id)
            record(makerspace, device, "printer_job_created", actor=actor, job=job, command=command)
            return job
    except IntegrityError as exc:
        raise PrinterConflict("External job or active request already has a printer job.") from exc
