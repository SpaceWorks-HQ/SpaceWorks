"""Typed printer provenance: credential-free snapshots plus remappable audit IDs."""
from apps.audit import services as audit
from apps.devices.models import DeviceEvent

PRINTER_ACTIONS = (
    "printer_bound", "printer_unbound", "printer_job_created", "command_leased",
    "command_acknowledged", "command_delivery_failed", "printer_telemetry_received",
    "printer_result_claimed", "printer_result_applied", "printer_result_needs_review",
    "printer_job_cancelled",
)


def record(makerspace, device, action, *, actor=None, command=None, job=None, machine=None, outcome="ok"):
    if action not in PRINTER_ACTIONS:
        raise ValueError("Unknown printer audit action.")
    command = command or (job.command if job else None)
    machine_id = job.machine_id if job else getattr(machine, "pk", None)
    request_id = job.service_request_id if job else None
    event = DeviceEvent.objects.create(
        makerspace=makerspace, device=device, device_id_snapshot=str(device.pk),
        device_name=device.name, device_key_version=device.key_version,
        event_type=action, outcome=outcome,
        command_id_snapshot=getattr(command, "pk", None),
        machine_id_snapshot=machine_id, service_request_id_snapshot=request_id,
    )
    audit.record(actor, f"devices.{action}", makerspace=makerspace, target=job or command or device,
                 meta={"device_id": str(device.pk), "device_key_version": device.key_version,
                       "operation_id": str(event.operation_id), "outcome": outcome,
                       "command_id": str(command.pk) if command else None,
                       "printer_job_id": str(job.pk) if job else None,
                       "machine_id": machine_id, "service_request_id": request_id})
    return event
