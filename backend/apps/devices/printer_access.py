"""Shared staff scope and locked adapter validation, without snapshot-based authority."""
from django.db.models import Q
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError

from apps.accounts import rbac
from apps.devices.models import Device, DeviceCommand, PrinterDeviceBinding, PrinterJob
from apps.devices.services_locks import lock_tenant
from apps.encryption.write_fence import assert_mapped_write_allowed
from apps.tenant_migration.gate_runtime import assert_write_allowed
from apps.machines.access import can_manage_machine, scope_manageable_machines_for_actor
from apps.machines.models import Machine, MachineServiceRequest
from apps.makerspaces.guards import require_module

ADAPTER_MODULES = ("devices", "machines", "machine_service")


def require_adapter(makerspace_id):
    for key in ADAPTER_MODULES:
        require_module(makerspace_id, key)


def authorize_staff(actor, makerspace_id, machine=None):
    require_adapter(makerspace_id)
    if not rbac.can(actor, rbac.Action.MANAGE_DEVICES, makerspace_id):
        raise PermissionDenied()
    if machine is not None and not can_manage_machine(actor, machine):
        raise PermissionDenied("Machine is outside your management scope.")


def scope_printers(actor, queryset):
    scoped = rbac.scope_by_action(actor, rbac.Action.MANAGE_DEVICES, queryset)
    machines = scope_manageable_machines_for_actor(actor, Machine.objects.all())
    historical = rbac.scope_by_action(actor, rbac.Action.MANAGE_MAKERSPACE, queryset).filter(machine__isnull=True)
    return scoped.filter(Q(machine_id__in=machines.values("pk")) | Q(pk__in=historical.values("pk")))


def lock_printer_tenant(makerspace_id):
    # Source gate -> PII fence -> tenant/domain rows, also before workflow PII writes.
    assert_write_allowed(makerspace_id)
    assert_mapped_write_allowed(makerspace_id)
    return lock_tenant(makerspace_id)


def locked_device(principal):
    makerspace = lock_printer_tenant(principal.makerspace_id)
    device = Device.objects.select_for_update().filter(pk=principal.device_id, makerspace=makerspace).first()
    if device is None or device.status != Device.Status.ACTIVE or device.key_version != principal.key_version:
        raise PermissionDenied("Device authorization is no longer active.")
    return makerspace, device


def owned_command(device, command_id):
    command = DeviceCommand.objects.select_for_update().filter(pk=command_id, device=device, makerspace_id=device.makerspace_id).first()
    if command is None:
        raise NotFound()
    if command.device_key_version != device.key_version:
        raise PermissionDenied("Command belongs to a previous device key.")
    return command


def live_target(job, device, *, require_running=True):
    """Caller owns tenant/device/command locks; acquire request then machine locks."""
    require_adapter(device.makerspace_id)
    if device.kind != Device.Kind.PRINTER or job.device_id != device.pk or job.makerspace_id != device.makerspace_id:
        raise ValidationError("Invalid printer job ownership.")
    request = MachineServiceRequest.objects.select_for_update().filter(pk=job.service_request_id, makerspace_id=device.makerspace_id).first()
    machine = Machine.objects.select_for_update().filter(pk=job.machine_id, makerspace_id=device.makerspace_id, is_active=True).first()
    binding = PrinterDeviceBinding.objects.select_for_update().filter(device=device, machine=machine, makerspace_id=device.makerspace_id, enabled=True).first() if machine else None
    if request is None or machine is None or binding is None or request.assigned_machine_id != machine.pk:
        raise ValidationError("Printer target is no longer available.")
    if require_running and request.status != MachineServiceRequest.Status.IN_PROGRESS:
        raise ValidationError("Printer request must be in progress.")
    return request, machine, binding


def owned_job(device, job_id):
    require_adapter(device.makerspace_id)
    if device.kind != Device.Kind.PRINTER:
        raise PermissionDenied("A printer device is required.")
    # Resolve identity first, then use the same command -> job lock order as delivery.
    identity = PrinterJob.objects.filter(pk=job_id, device=device, makerspace_id=device.makerspace_id).values("command_id").first()
    if identity is None:
        raise NotFound()
    command = owned_command(device, identity["command_id"])
    job = PrinterJob.objects.select_for_update().get(pk=job_id)
    return job, command
