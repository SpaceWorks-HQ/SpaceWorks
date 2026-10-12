"""Printer binding mutations are authorized and audited under the tenant/device locks."""
from django.db import IntegrityError, transaction
from rest_framework.exceptions import NotFound, ValidationError

from apps.accounts import rbac
from apps.devices.errors_printers import PrinterConflict
from apps.devices.models import Device, DeviceCommand, PrinterDeviceBinding, PrinterJob
from apps.devices.printer_access import authorize_staff, scope_printers
from apps.devices.services_locks import lock_tenant
from apps.devices.services_printer_events import record
from apps.machines.access import scope_manageable_machines_for_actor
from apps.machines.models import Machine


def create_binding(actor, makerspace_id, *, device_id, machine_id, enabled=True, auto_apply_terminal=False):
    if type(enabled) is not bool or type(auto_apply_terminal) is not bool:
        raise ValidationError("Binding policies must be boolean.")
    try:
        with transaction.atomic():
            makerspace = lock_tenant(makerspace_id)
            authorize_staff(actor, makerspace_id)
            # Authorize through the scoped querysets WITHOUT a lock, then lock the single row
            # by primary key: machine scoping adds DISTINCT, and Postgres refuses
            # SELECT ... FOR UPDATE on a DISTINCT query.
            device_in_scope = rbac.scope_by_action(actor, rbac.Action.MANAGE_DEVICES, Device.objects.all()).filter(pk=device_id, makerspace=makerspace).exists()
            machine_in_scope = scope_manageable_machines_for_actor(actor, Machine.objects.all()).filter(pk=machine_id, makerspace=makerspace).exists()
            device = Device.objects.select_for_update().filter(pk=device_id, makerspace=makerspace).first() if device_in_scope else None
            machine = Machine.objects.select_for_update().filter(pk=machine_id, makerspace=makerspace).first() if machine_in_scope else None
            if device is None or machine is None:
                raise ValidationError("Device and machine must belong to this management scope.")
            authorize_staff(actor, makerspace_id, machine)
            if device.kind != Device.Kind.PRINTER or device.status != Device.Status.ACTIVE or not machine.is_active:
                raise ValidationError("An active printer device and machine are required.")
            binding = PrinterDeviceBinding.objects.create(makerspace=makerspace, device=device, machine=machine,
                enabled=enabled, auto_apply_terminal=auto_apply_terminal, created_by=actor)
            record(makerspace, device, "printer_bound", actor=actor, machine=machine)
            return binding
    except IntegrityError as exc:
        raise PrinterConflict("Device or machine already has a binding.") from exc


def update_binding(actor, binding_id, changes):
    if set(changes) - {"enabled", "auto_apply_terminal"} or any(type(v) is not bool for v in changes.values()):
        raise ValidationError("Only boolean binding policies may be changed.")
    identity = scope_printers(actor, PrinterDeviceBinding.objects.all()).filter(pk=binding_id).values("makerspace_id", "device_id").first()
    if identity is None:
        raise NotFound()
    with transaction.atomic():
        makerspace = lock_tenant(identity["makerspace_id"])
        device = Device.objects.select_for_update().filter(pk=identity["device_id"], makerspace=makerspace).first()
        binding = PrinterDeviceBinding.objects.select_for_update().filter(pk=binding_id, makerspace=makerspace, device=device).first()
        if device is None or binding is None:
            raise NotFound()
        authorize_staff(actor, makerspace.pk, binding.machine)
        if not scope_printers(actor, PrinterDeviceBinding.objects.all()).filter(pk=binding.pk).exists():
            raise NotFound()
        if changes.get("enabled") and (binding.machine is None or not binding.machine.is_active or device.status != "active"):
            raise ValidationError("Binding has no active target.")
        for field, value in changes.items():
            setattr(binding, field, value)
        binding.save(update_fields=[*changes, "updated_at"])
        if not binding.enabled:
            _cancel_binding_jobs(makerspace, device, actor)
        record(makerspace, device, "printer_bound" if binding.enabled else "printer_unbound", actor=actor, machine=binding.machine)
        return binding


def _cancel_binding_jobs(makerspace, device, actor):
    from .services_commands import cancel_command

    for command in DeviceCommand.objects.select_for_update().filter(device=device).order_by("id"):
        job = PrinterJob.objects.select_for_update().filter(command=command).first()
        if job and job.state not in {"applied", "cancelled"}:
            cancel_command(makerspace, device, command, job=job, code="binding_disabled", actor=actor)


def delete_binding(actor, binding_id):
    identity = scope_printers(actor, PrinterDeviceBinding.objects.all()).filter(pk=binding_id).values("makerspace_id", "device_id").first()
    if identity is None:
        raise NotFound()
    with transaction.atomic():
        makerspace = lock_tenant(identity["makerspace_id"])
        device = Device.objects.select_for_update().filter(pk=identity["device_id"], makerspace=makerspace).first()
        binding = PrinterDeviceBinding.objects.select_for_update().filter(pk=binding_id, makerspace=makerspace, device=device).first()
        if device is None or binding is None:
            raise NotFound()
        authorize_staff(actor, makerspace.pk, binding.machine)
        if not scope_printers(actor, PrinterDeviceBinding.objects.all()).filter(pk=binding.pk).exists():
            raise NotFound()
        _cancel_binding_jobs(makerspace, device, actor)
        record(makerspace, device, "printer_unbound", actor=actor, machine=binding.machine)
        binding.delete()
