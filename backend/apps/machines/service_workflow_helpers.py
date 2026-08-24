from django.core.exceptions import ValidationError
from django.db import transaction

from apps.audit import services as audit
from apps.makerspaces.platform import module_enabled
from apps.machines.models import Machine, MachineServiceRequest, ServiceBucket, ServiceQueue
from apps.machines.service_emails import notify_service_status
from apps.machines.service_errors import ServiceConsumptionInvalid, ServiceInvalidTransition, ServiceMachineUnavailable
from apps.machines.printer_capabilities import is_printer_type, validate_service_payload


_ALLOWED = {
    MachineServiceRequest.Status.PENDING: {MachineServiceRequest.Status.ACCEPTED, MachineServiceRequest.Status.REJECTED},
    MachineServiceRequest.Status.ACCEPTED: {MachineServiceRequest.Status.IN_PROGRESS},
    MachineServiceRequest.Status.IN_PROGRESS: {MachineServiceRequest.Status.COMPLETED, MachineServiceRequest.Status.FAILED},
    MachineServiceRequest.Status.COMPLETED: {MachineServiceRequest.Status.COLLECTED},
}


def _locked_submission_target(target):
    if isinstance(target, ServiceQueue):
        queue = ServiceQueue.objects.select_for_update().select_related("makerspace", "machine_type").get(pk=target.pk)
        if queue.machine_type.makerspace_id not in (None, queue.makerspace_id):
            raise ServiceMachineUnavailable("Service queue machine type is outside its makerspace.")
        return queue
    if isinstance(target, ServiceBucket):
        bucket = ServiceBucket.objects.select_related("machine__makerspace").get(pk=target.pk)
        return Machine.objects.select_for_update().select_related("makerspace").get(pk=bucket.machine_id)
    return Machine.objects.select_for_update().select_related("makerspace").get(pk=target.pk)


def _locked_submission_machine(target):
    """Legacy helper retained for per-machine callers and their lock ordering."""
    return _locked_submission_target(target)


def _assert_submission_write_allowed(target):
    from apps.encryption.write_fence import assert_mapped_write_allowed
    if isinstance(target, ServiceQueue):
        makerspace_id = ServiceQueue.objects.only("makerspace_id").get(pk=target.pk).makerspace_id
    else:
        machine_id = target.machine_id if isinstance(target, ServiceBucket) else target.pk
        makerspace_id = Machine.objects.only("makerspace_id").get(pk=machine_id).makerspace_id
    assert_mapped_write_allowed(makerspace_id)


def _assert_request_write_allowed(service_request):
    from apps.encryption.write_fence import assert_mapped_write_allowed
    makerspace_id = MachineServiceRequest.objects.filter(pk=service_request.pk).values_list("makerspace_id", flat=True).get()
    assert_mapped_write_allowed(makerspace_id)


def _locked_request(service_request):
    return MachineServiceRequest.objects.select_for_update(of=("self",)).select_related("bucket__machine__makerspace", "queue__makerspace", "queue__machine_type", "requester", "assigned_machine", "run_consumable_pool").get(pk=service_request.pk)


def _lock_assigned_machine(service_request):
    if not service_request.assigned_machine_id:
        raise ServiceMachineUnavailable("No machine is assigned to this service request.")
    return Machine.objects.select_for_update().get(pk=service_request.assigned_machine_id)


def _release_queue_machine(service_request):
    if service_request.assigned_machine_id:
        machine = Machine.objects.select_for_update().get(pk=service_request.assigned_machine_id)
        if machine.status == Machine.Status.RUNNING:
            machine.status = Machine.Status.IDLE
            machine.save(update_fields=["status", "updated_at"])


def _require_available(machine):
    if not machine.is_active or machine.status != Machine.Status.IDLE:
        raise ServiceMachineUnavailable("Machine is not available for service requests.")


def _require_module(makerspace, *, locked=False):
    # `locked=True` re-reads the makerspace under `select_for_update` so a
    # concurrent uninstall cannot commit between this check and the create
    # (plan A8). The error shape is deliberately identical either way.
    if locked:
        from apps.makerspaces.models import Makerspace

        makerspace = Makerspace.objects.select_for_update().get(pk=makerspace.pk)
    if not module_enabled(makerspace, "machine_service"):
        raise ValidationError("Machine service is disabled for this makerspace.")


def _require_edge(service_request, next_status):
    if next_status not in _ALLOWED.get(service_request.status, set()):
        raise ServiceInvalidTransition(f"Cannot transition machine service request from {service_request.status} to {next_status}.")


def _minutes(value, field):
    if isinstance(value, bool):
        raise ServiceConsumptionInvalid(f"{field} must be a non-negative whole number.")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ServiceConsumptionInvalid(f"{field} must be a non-negative whole number.") from exc
    if parsed < 0 or str(value).strip() not in {str(parsed), f"{parsed}.0"}:
        raise ServiceConsumptionInvalid(f"{field} must be a non-negative whole number.")
    return parsed


def _percent(value):
    parsed = _minutes(value, "percent_complete")
    if parsed > 100:
        raise ServiceConsumptionInvalid("percent_complete must be between 0 and 100.")
    return parsed


def _decimal(value, field):
    from decimal import Decimal, InvalidOperation
    try:
        parsed = Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ServiceConsumptionInvalid(f"{field} must be numeric.") from exc
    if not parsed.is_finite():
        raise ServiceConsumptionInvalid(f"{field} must be finite.")
    return parsed


def _validate_capability_payload(machine_type, payload):
    try:
        validate_service_payload(machine_type, payload)
    except ValidationError as exc:
        raise ServiceConsumptionInvalid(exc.message_dict if hasattr(exc, "message_dict") else exc.messages[0]) from exc


def _require_printer_start_inputs(service_request, machine, consumable_pool_id, planned_grams):
    """A printer run must snapshot a real plan and compatible material at start."""
    if not is_printer_type(machine.machine_type):
        return
    if service_request.estimated_minutes <= 0:
        raise ServiceConsumptionInvalid("Printer service requires positive estimated_minutes before starting.")
    if consumable_pool_id is None or planned_grams is None:
        raise ServiceConsumptionInvalid("Printer service requires a consumable pool and planned grams before starting.")


def _audit_transition(actor, service_request, event, extra=None):
    meta = {"request_id": service_request.pk, "status": service_request.status, "estimated_minutes": service_request.estimated_minutes, "actual_minutes": service_request.actual_minutes}
    if extra:
        meta.update(extra)
    audit.record(actor, f"machine_service.{event}", makerspace=service_request.makerspace, target=service_request, meta=meta)


def _notify_after_commit(service_request, event):
    request_id = service_request.pk
    transaction.on_commit(lambda: notify_service_status(MachineServiceRequest.objects.select_related("bucket__machine__makerspace", "queue__makerspace").get(pk=request_id), event))
