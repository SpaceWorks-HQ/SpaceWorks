"""Hooks for 7b's generic delivery. Adapter state never owns a second lease protocol."""
from django.db import transaction
from django.utils import timezone

from apps.devices.errors_labels import LabelConflict, LabelGone
from apps.devices.label_access import locked_batch, locked_label_device, owned_label
from apps.devices.models import LabelPrintCommand
from apps.devices.services_label_events import record
from apps.operations.qr_zip import build_batch_zip


def fail_label(makerspace, device, command, *, label=None, code="delivery_failed"):
    label = label or LabelPrintCommand.objects.select_for_update().filter(command=command).first()
    if label is not None and label.result not in ["succeeded", "failed"]:
        label.result = LabelPrintCommand.Result.FAILED
        label.result_code = code
        label.result_message = "Label delivery is no longer available."
        label.completed_at = timezone.now()
        label.save(update_fields=["result", "result_code", "result_message", "completed_at"])
        record(makerspace, device, "label_command_failed", label, command)


def cancel_label(makerspace, device, command, *, label=None, code="target_unavailable"):
    from apps.devices.models_commands import DeviceCommand

    command.status = DeviceCommand.Status.CANCELLED
    command.last_error_code = code
    command.lease_token_digest = None
    command.lease_expires_at = None
    command.save(update_fields=["status", "last_error_code", "lease_token_digest", "lease_expires_at", "updated_at"])
    fail_label(makerspace, device, command, label=label, code=code)


def lease_payload(label):
    return {"label_command_id": label.pk, "qr_batch_id": label.batch_id,
            "item_count": label.item_count_snapshot}


def command_content(principal, label_id):
    error = None
    with transaction.atomic():
        makerspace, device = locked_label_device(principal)
        label, command = owned_label(device, label_id)
        if label.result in ["succeeded", "failed"]:
            raise LabelConflict("A terminal command cannot download labels again.")
        batch = locked_batch(label, device)
        if batch is None:
            cancel_label(makerspace, device, command, label=label)
            error = LabelGone()
        else:
            content = build_batch_zip(batch)
            record(makerspace, device, "label_content_downloaded", label, command)
    if error is not None:
        raise error
    return content, f"qr-labels-{label.pk}.zip"
