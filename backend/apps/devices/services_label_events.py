"""Only typed identities and fixed outcomes enter provenance, never device text."""
from apps.audit import services as audit
from apps.devices.models import DeviceEvent

LABEL_ACTIONS = (
    "label_command_created", "label_content_downloaded", "label_command_succeeded",
    "label_command_retry_scheduled", "label_command_failed",
)


def record(makerspace, device, action, label, command, *, actor=None, operation_id=None):
    if action not in LABEL_ACTIONS:
        raise ValueError("Unknown label audit action.")
    event = DeviceEvent.objects.create(
        makerspace=makerspace, device=device, device_id_snapshot=str(device.pk),
        device_name=device.name, device_key_version=device.key_version,
        event_type=action, outcome=label.result,
        command_id_snapshot=command.pk, qr_batch_id_snapshot=label.batch_id_snapshot,
        **({"operation_id": operation_id} if operation_id is not None else {}),
    )
    audit.record(actor, f"devices.{action}", makerspace=makerspace, target=label,
                 meta={"device_id": str(device.pk), "device_key_version": device.key_version,
                       "command_id": str(command.pk),
                       "label_command_id": str(label.pk), "qr_batch_id": label.batch_id,
                       "operation_id": str(event.operation_id), "outcome": label.result})
    return event
