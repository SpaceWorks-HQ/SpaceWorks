"""Durable claim precedes any workflow effect; identical reports share one claim."""
import hashlib
import json

from django.db import IntegrityError, connection, transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.devices.errors_printers import PrinterConflict
from apps.devices.models import PrinterJob, PrinterJobConsumption
from apps.devices.printer_access import live_target, locked_device, owned_job
from apps.devices.serializers_printers import ResultSerializer, TelemetrySerializer
from apps.devices.services_printer_events import record
from apps.machines.models import MachineConsumable


def fingerprint(payload):
    canonical = dict(payload)
    canonical["consumptions"] = sorted(canonical["consumptions"], key=lambda row: row["machine_consumable_id"])
    return hashlib.sha256(json.dumps(canonical, default=str, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def validate_measurements(request, machine, payload):
    grams, quantity = payload["actual_grams"], payload["actual_quantity"]
    if request.run_consumable_pool_id:
        # The workflow supports one pool reconciliation plus separate MachineConsumable inputs.
        weight = request.metering_unit == "weight"
        if (grams is None if weight else quantity is None) or (quantity is not None if weight else grams is not None):
            raise ValidationError("Supply the actual measurement matching the reserved pool's metering unit.")
    elif grams is not None or quantity is not None:
        raise ValidationError("This request has no reserved consumable pool to reconcile.")
    ids = [row["machine_consumable_id"] for row in payload["consumptions"]]
    consumables = {row.pk: row for row in MachineConsumable.objects.select_for_update().filter(pk__in=ids, machine=machine).order_by("pk")}
    if set(consumables) != set(ids):
        raise ValidationError("Every consumption must belong to the assigned machine.")
    for item in payload["consumptions"]:
        row = consumables[item["machine_consumable_id"]]
        if row.measurement == "count" and item["quantity"] != item["quantity"].to_integral_value():
            raise ValidationError("Count consumption must be a whole number.")
    return consumables


def claim_result(principal, job_id, data):
    serializer = ResultSerializer(data=data)
    serializer.is_valid(raise_exception=True)
    payload = serializer.validated_data
    digest = fingerprint(payload)
    try:
        with transaction.atomic():
            makerspace, device = locked_device(principal)
            job, command = owned_job(device, job_id)
            if command.status != "acknowledged" or job.state == "cancelled":
                raise PrinterConflict("Result requires an acknowledged command.")
            if payload["external_job_id"] != job.external_job_id:
                raise PrinterConflict("External job identity does not match.")
            if job.reported_at is not None:
                if job.terminal_operation_id != payload["operation_id"] or job.report_sha256 != digest:
                    raise PrinterConflict("Terminal report is immutable.")
                return job, False
            request, machine, binding = live_target(job, device)
            consumables = validate_measurements(request, machine, payload)
            if PrinterJob.objects.filter(device=device, terminal_operation_id=payload["operation_id"]).exclude(pk=job.pk).exists():
                raise PrinterConflict("Operation identity has already been used.")
            job.terminal_operation_id = payload["operation_id"]
            job.report_sha256 = digest
            job.reported_at = timezone.now()
            for field in ("outcome", "actual_minutes", "failure_reason", "percent_complete", "actual_grams", "actual_quantity"):
                setattr(job, field, payload[field])
            job.state = "reported" if binding.auto_apply_terminal else "needs_review"
            job.save(update_fields=["terminal_operation_id", "report_sha256", "reported_at", "outcome", "actual_minutes",
                                   "failure_reason", "percent_complete", "actual_grams", "actual_quantity", "state"])
            with connection.cursor() as cursor:
                cursor.execute("SELECT set_config('app.printer_claim_job', %s, true)", [str(job.pk)])
            for item in payload["consumptions"]:
                PrinterJobConsumption.objects.create(job=job, machine_consumable=consumables[item["machine_consumable_id"]],
                    machine_consumable_id_snapshot=item["machine_consumable_id"], quantity=item["quantity"])
            record(makerspace, device, "printer_result_claimed", job=job, command=command, outcome=job.outcome)
            if job.state == "needs_review":
                record(makerspace, device, "printer_result_needs_review", job=job, command=command, outcome="manual_approval")
            return job, True
    except IntegrityError as exc:
        raise PrinterConflict("Operation identity conflicts with an existing report.") from exc


def telemetry(principal, job_id, data):
    serializer = TelemetrySerializer(data=data)
    serializer.is_valid(raise_exception=True)
    payload = serializer.validated_data
    with transaction.atomic():
        makerspace, device = locked_device(principal)
        job, command = owned_job(device, job_id)
        if command.status != "acknowledged" or job.state != "awaiting":
            raise PrinterConflict("Telemetry requires an acknowledged nonterminal job.")
        live_target(job, device)
        if payload["external_job_id"] != job.external_job_id:
            raise PrinterConflict("External job identity does not match.")
        now = timezone.now()
        job.telemetry_state = payload["telemetry_state"]
        job.progress_percent = payload["progress_percent"]
        job.telemetry_at = now
        job.save(update_fields=["telemetry_state", "progress_percent", "telemetry_at"])
        device.last_seen_at = now
        device.save(update_fields=["last_seen_at"])
        record(makerspace, device, "printer_telemetry_received", job=job, command=command)
        return job
