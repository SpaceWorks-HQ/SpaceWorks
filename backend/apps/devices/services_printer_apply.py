"""Two-transaction claim/application boundary; all effects use the existing workflow."""
import logging

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import NotFound, ValidationError

from apps.devices.errors_printers import PrinterConflict
from apps.devices.models import Device, PrinterJob
from apps.devices.principal import DevicePrincipal
from apps.devices.printer_access import authorize_staff, live_target, locked_device, owned_job, scope_printers
from apps.devices.services_printer_events import record
from apps.devices.services_printer_reports import claim_result, fingerprint, validate_measurements
from apps.machines import service_workflow_actions as workflow


logger = logging.getLogger(__name__)


class WorkflowApplicationFailed(Exception):
    pass


def _apply(principal, job_id, *, actor=None):
    with transaction.atomic():
        makerspace, device = locked_device(principal)
        job, command = owned_job(device, job_id)
        if actor is not None:
            authorize_staff(actor, makerspace.pk, job.machine)
            if not scope_printers(actor, PrinterJob.objects.all()).filter(pk=job.pk).exists():
                raise NotFound()
        if job.state == "applied":
            return job
        if command.status != "acknowledged" or job.state not in {"reported", "needs_review"} or job.reported_at is None:
            raise PrinterConflict("No terminal claim is available for application.")
        request, machine, binding = live_target(job, device)
        if actor is None and (job.state != "reported" or not binding.auto_apply_terminal):
            return job
        rows = list(job.consumptions.select_related("machine_consumable").all())
        if any(row.machine_consumable is None or row.machine_consumable.machine_id != machine.pk for row in rows):
            raise ValidationError("A claimed consumable target is no longer available.")
        consumptions = [{"machine_consumable_id": row.machine_consumable_id, "quantity": row.quantity} for row in rows]
        payload = {"operation_id": job.terminal_operation_id, "external_job_id": job.external_job_id,
                   "outcome": job.outcome, "actual_minutes": job.actual_minutes, "failure_reason": job.failure_reason,
                   "percent_complete": job.percent_complete, "actual_grams": job.actual_grams,
                   "actual_quantity": job.actual_quantity, "consumptions": consumptions}
        if fingerprint(payload) != job.report_sha256:
            raise PrinterConflict("Stored report integrity check failed.")
        validate_measurements(request, machine, payload)
        kwargs = {"actual_minutes": job.actual_minutes, "consumptions": consumptions}
        if job.actual_quantity is not None:
            kwargs["actual_quantity"] = job.actual_quantity
        if job.actual_grams is not None:
            kwargs["actual_grams"] = job.actual_grams
        # Workflow, applied marker and provenance share one rollback boundary. Admission failures remain refusals.
        try:
            if job.outcome == "completed":
                workflow.complete(request, actor, **kwargs)
            else:
                workflow.fail(request, actor, reason=job.failure_reason, percent_complete=job.percent_complete, **kwargs)
            job.state = "applied"
            job.applied_at = timezone.now()
            job.processed_by = actor
            job.save(update_fields=["state", "applied_at", "processed_by"])
            record(makerspace, device, "printer_result_applied", actor=actor, job=job, command=command, outcome=job.outcome)
            return job
        except Exception as exc:
            raise WorkflowApplicationFailed() from exc


def apply_report(principal, job_id, *, actor=None):
    try:
        return _apply(principal, job_id, actor=actor)
    except WorkflowApplicationFailed:
        logger.warning("Printer workflow application failed", extra={
            "printer_job_id": str(job_id), "device_id": str(principal.device_id),
            "error_code": "workflow_application_failed",
        })
        # This transaction cannot roll back the committed claim; no traceback/report is logged.
        with transaction.atomic():
            makerspace, device = locked_device(principal)
            job, command = owned_job(device, job_id)
            if job.state == "applied":
                return job
            job.state = "needs_review"
            job.save(update_fields=["state"])
            command.last_error_code = "workflow_application_failed"
            command.save(update_fields=["last_error_code", "updated_at"])
            record(makerspace, device, "printer_result_needs_review", actor=actor, job=job, command=command,
                   outcome="workflow_application_failed")
            return job


def report_result(principal, job_id, data):
    job, _claimed = claim_result(principal, job_id, data)
    # A crash after claim may leave REPORTED; matching retry safely resumes that state.
    # NEEDS_REVIEW is never retried automatically.
    if job.state == "reported":
        return apply_report(principal, job_id)
    return job


def approve_report(actor, job_id):
    job = scope_printers(actor, PrinterJob.objects.all()).filter(pk=job_id).first()
    if job is None:
        raise NotFound()
    authorize_staff(actor, job.makerspace_id, job.machine)
    device = Device.objects.filter(pk=job.device_id, makerspace_id=job.makerspace_id).first()
    if device is None:
        raise NotFound()
    return apply_report(DevicePrincipal.from_device(device), job_id, actor=actor)
