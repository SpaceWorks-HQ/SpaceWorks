"""At-least-once delivery, DB ownership and bounded lazy expiry (no scheduler needed)."""
import secrets
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.devices import protocol
from apps.devices.errors_printers import LeaseExpired, PrinterConflict
from apps.devices.models import DeviceCommand, PrinterJob
from apps.devices.printer_access import live_target, locked_device, owned_command
from apps.devices.services_printer_events import record


def retry_at(now, attempts):
    return now + timedelta(seconds=min(3600, 2 ** min(attempts, 12)))


def cancel_command(makerspace, device, command, *, job=None, code="target_unavailable", actor=None):
    if command.kind == "label_print":
        from apps.devices.services_label_delivery import cancel_label
        cancel_label(makerspace, device, command, label=job, code=code)
        return
    command.status = DeviceCommand.Status.CANCELLED
    command.last_error_code = code
    command.lease_token_digest = None
    command.lease_expires_at = None
    command.save(update_fields=["status", "last_error_code", "lease_token_digest", "lease_expires_at", "updated_at"])
    if job and job.state != PrinterJob.State.APPLIED:
        job.state = PrinterJob.State.CANCELLED
        job.save(update_fields=["state"])
    record(makerspace, device, "printer_job_cancelled", actor=actor, command=command, job=job, outcome=code)


def validate_delivery_target(makerspace, device, command):
    if command.kind == "label_print":
        from apps.devices.label_access import delivery_target
        label = delivery_target(makerspace, device, command)
        if label is None:
            cancel_command(makerspace, device, command)
        return label
    # Unknown kinds are never delivered.
    job = PrinterJob.objects.select_for_update().filter(command=command).first()
    try:
        if command.device_key_version != device.key_version or command.kind != "printer_job" or job is None:
            raise ValidationError("Unknown or stale command.")
        live_target(job, device)
    except ValidationError:
        cancel_command(makerspace, device, command, job=job)
        return None
    return job


def expire_lease(makerspace, device, command, now, *, job=None):
    if command.status != DeviceCommand.Status.LEASED or command.lease_expires_at > now:
        return False
    failed = command.attempts >= settings.DEVICE_COMMAND_MAX_ATTEMPTS
    command.status = DeviceCommand.Status.DELIVERY_FAILED if failed else DeviceCommand.Status.QUEUED
    command.next_attempt_at = retry_at(now, command.attempts)
    command.lease_token_digest = None
    command.lease_expires_at = None
    command.last_error_code = "lease_expired"
    command.save(update_fields=["status", "next_attempt_at", "lease_token_digest", "lease_expires_at", "last_error_code", "updated_at"])
    if failed:
        if command.kind == "label_print":
            from apps.devices.services_label_delivery import fail_label
            fail_label(makerspace, device, command, label=job, code="lease_expired")
        elif job:
            job.state = PrinterJob.State.CANCELLED
            job.save(update_fields=["state"])
        record(makerspace, device, "command_delivery_failed", command=command,
               job=job if command.kind == "printer_job" else None,
               label=job if command.kind == "label_print" else None, outcome="lease_expired")
    return True


def lease_command(principal, *, now=None):
    now = now or timezone.now()
    with transaction.atomic():
        makerspace, device = locked_device(principal)
        candidates = DeviceCommand.objects.select_for_update(skip_locked=True).filter(
            device=device, makerspace=makerspace, status__in=["queued", "leased"],
            next_attempt_at__lte=now).order_by("created_at", "id")
        for command in candidates:
            job = validate_delivery_target(makerspace, device, command)
            if job is None:
                continue
            if expire_lease(makerspace, device, command, now, job=job):
                continue
            if command.status != DeviceCommand.Status.QUEUED:
                continue
            if command.attempts >= settings.DEVICE_COMMAND_MAX_ATTEMPTS:
                command.status = DeviceCommand.Status.DELIVERY_FAILED
                command.save(update_fields=["status", "updated_at"])
                if command.kind == "label_print":
                    from apps.devices.services_label_delivery import fail_label
                    fail_label(makerspace, device, command, label=job, code="attempts_exhausted")
                else:
                    job.state = PrinterJob.State.CANCELLED
                    job.save(update_fields=["state"])
                record(makerspace, device, "command_delivery_failed", command=command,
                       job=job if command.kind == "printer_job" else None,
                       label=job if command.kind == "label_print" else None, outcome="attempts_exhausted")
                continue
            token = secrets.token_urlsafe(32)
            command.status = DeviceCommand.Status.LEASED
            command.attempts += 1
            command.lease_token_digest = protocol.sha256_hex(token.encode("ascii"))
            command.lease_expires_at = now + timedelta(seconds=settings.DEVICE_COMMAND_LEASE_SECONDS)
            command.save(update_fields=["status", "attempts", "lease_token_digest", "lease_expires_at", "updated_at"])
            record(makerspace, device, "command_leased", command=command,
                   job=job if command.kind == "printer_job" else None,
                   label=job if command.kind == "label_print" else None)
            payload = {"command_id": command.pk, "kind": command.kind, "lease_token": token,
                       "lease_expires_at": command.lease_expires_at}
            if command.kind == "label_print":
                from apps.devices.services_label_delivery import lease_payload
                payload.update(lease_payload(job))
            else:
                payload.update(printer_job_id=job.pk, external_job_id=job.external_job_id,
                               service_request_id=job.service_request_id)
            return payload
    return None


def acknowledge(principal, command_id, lease_token, *, now=None):
    now = now or timezone.now()
    error = None
    with transaction.atomic():
        makerspace, device = locked_device(principal)
        command = owned_command(device, command_id)
        digest = protocol.sha256_hex(str(lease_token).encode("utf-8"))
        if command.lease_token_digest is None or not secrets.compare_digest(command.lease_token_digest, digest):
            raise PrinterConflict("Lease token does not own this command.")
        if command.status == DeviceCommand.Status.ACKNOWLEDGED:
            return command
        if command.kind == "label_print" and command.status != DeviceCommand.Status.LEASED:
            # A late ack must not turn terminal print history into cancellation or
            # invalidate its immutable result receipt merely by polling again.
            raise PrinterConflict()
        job = validate_delivery_target(makerspace, device, command)
        if job is None:
            error = PrinterConflict("Command target is no longer available.")
        elif expire_lease(makerspace, device, command, now, job=job):
            error = LeaseExpired()
        elif command.status != DeviceCommand.Status.LEASED:
            error = PrinterConflict()
        else:
            command.status = DeviceCommand.Status.ACKNOWLEDGED
            command.acknowledged_at = now
            command.save(update_fields=["status", "acknowledged_at", "updated_at"])
            record(makerspace, device, "command_acknowledged", command=command,
                   job=job if command.kind == "printer_job" else None,
                   label=job if command.kind == "label_print" else None)
    # Expiry and cancellation must survive the 410/409 response.
    if error:
        raise error
    return command
