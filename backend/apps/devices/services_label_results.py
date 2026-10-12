"""Atomic result receipt + command update: a matching replay cannot queue twice."""
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied

from apps.devices.errors_labels import LabelConflict, LabelGone
from apps.devices.label_access import locked_batch, locked_label_device, owned_label
from apps.devices.models import LabelPrintCommand, LabelPrintResult
from apps.devices.serializers_labels import LabelResultSerializer, RESULT_MESSAGES
from apps.devices.services_label_events import record
from apps.devices.services_commands import retry_at


def report_result(principal, label_id, *, operation_id, outcome, result_code, now=None):
    from apps.devices.models_commands import DeviceCommand

    validator = LabelResultSerializer(data={"operation_id": operation_id,
        "outcome": outcome, "result_code": result_code})
    validator.is_valid(raise_exception=True)
    operation_id = validator.validated_data["operation_id"]
    now = now or timezone.now()
    error = None
    with transaction.atomic():
        makerspace, device = locked_label_device(principal)
        # Look for the receipt before requiring acknowledged state: a previous failure
        # may have requeued, or later results may already have finished this command.
        previous = LabelPrintResult.objects.filter(makerspace=makerspace, operation_id=operation_id).first()
        if previous is not None:
            label = LabelPrintCommand.objects.get(pk=previous.label_command_id)
            if (label.pk != label_id or label.device_id != device.pk
                    or previous.outcome != outcome or previous.result_code != result_code):
                raise LabelConflict("Operation ID has already been used for another payload.")
            # Key rotation/revocation must also invalidate cached result authority.
            if label.command.device_key_version != device.key_version:
                raise PermissionDenied("Command belongs to a previous device key.")
            if label.command.status == DeviceCommand.Status.CANCELLED:
                raise LabelConflict("Command has been cancelled.")
            return previous
        label, command = owned_label(device, label_id)
        if locked_batch(label, device) is None:
            from apps.devices.services_label_delivery import cancel_label
            cancel_label(makerspace, device, command, label=label)
            error = LabelGone()
        elif label.result in [LabelPrintCommand.Result.SUCCEEDED, LabelPrintCommand.Result.FAILED]:
            raise LabelConflict("A terminal command cannot accept another result.")
        else:
            result = outcome
            if outcome == LabelPrintCommand.Result.RETRYABLE_FAILED:
                if command.attempts >= settings.DEVICE_COMMAND_MAX_ATTEMPTS:
                    result = LabelPrintCommand.Result.FAILED
                else:
                    command.status = DeviceCommand.Status.QUEUED
                    command.next_attempt_at = retry_at(now, command.attempts)
                    command.lease_token_digest = None
                    command.lease_expires_at = None
                    command.acknowledged_at = None
            if result == LabelPrintCommand.Result.FAILED:
                command.status = DeviceCommand.Status.DELIVERY_FAILED
            command.last_error_code = "" if result == "succeeded" else result_code
            command.save(update_fields=["status", "next_attempt_at", "lease_token_digest",
                "lease_expires_at", "acknowledged_at", "last_error_code", "updated_at"])
            label.result = result
            label.result_code = result_code
            label.result_message = RESULT_MESSAGES[result_code]
            label.completed_at = now if result in ["succeeded", "failed"] else None
            label.save(update_fields=["result", "result_code", "result_message", "completed_at"])
            receipt = LabelPrintResult.objects.create(makerspace=makerspace, label_command=label,
                operation_id=operation_id, outcome=outcome, result_code=result_code,
                response_result=result, response_command_status=command.status,
                response_completed_at=label.completed_at)
            action = {"succeeded": "label_command_succeeded", "failed": "label_command_failed",
                      "retryable_failed": "label_command_retry_scheduled"}[result]
            record(makerspace, device, action, label, command, operation_id=operation_id)
    if error is not None:
        raise error
    return receipt
