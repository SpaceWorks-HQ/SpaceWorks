"""The sole state-transition authority for machine service requests."""

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.audit import services as audit
from apps.makerspaces import limits
from apps.makerspaces.platform import module_enabled
from apps.machines import role_scope
from apps.machines.models import Machine, MachineServiceRequest, ServiceBucket, ServiceQueue, get_or_create_default_bucket
from apps.machines.service_consumption import debit_consumptions
from apps.machines.service_emails import notify_service_status
from apps.machines.service_errors import ServiceConsumptionInvalid, ServiceInvalidTransition, ServiceMachineUnavailable
from apps.machines.printer_capabilities import is_printer_type, validate_service_payload


_ALLOWED = {
    MachineServiceRequest.Status.PENDING: {MachineServiceRequest.Status.ACCEPTED, MachineServiceRequest.Status.REJECTED},
    MachineServiceRequest.Status.ACCEPTED: {MachineServiceRequest.Status.IN_PROGRESS},
    MachineServiceRequest.Status.IN_PROGRESS: {MachineServiceRequest.Status.COMPLETED, MachineServiceRequest.Status.FAILED},
    MachineServiceRequest.Status.COMPLETED: {MachineServiceRequest.Status.COLLECTED},
}


def submit(bucket_or_machine, requester, *, requester_name, contact_email, contact_phone, title, description="", source_link="", actor=None, member=None, capability_payload=None):
    """Create a pending legacy bucket request or unassigned pooled request."""
    with transaction.atomic():
        _assert_submission_write_allowed(bucket_or_machine)
        target = _locked_submission_target(bucket_or_machine) if isinstance(bucket_or_machine, ServiceQueue) else _locked_submission_machine(bucket_or_machine)
        makerspace = target.makerspace
        machine_type = target.machine_type if isinstance(target, ServiceQueue) else target.machine_type
        _validate_capability_payload(machine_type, capability_payload or {})
        _require_module(makerspace, locked=True)
        limits.check_quota(makerspace, "machine_service_open", adding=1)
        limits.check_quota(makerspace, "machine_service_submit", adding=1)
        if isinstance(target, ServiceQueue):
            if not target.is_active:
                raise ServiceMachineUnavailable("Service queue is inactive.")
            bucket, queue, assigned = None, target, None
        else:
            _require_available(target)
            bucket = get_or_create_default_bucket(target, makerspace=makerspace)
            queue, assigned = None, target
        service_request = MachineServiceRequest.objects.create(
            bucket=bucket, queue=queue, makerspace=makerspace, requester=requester, member=member,
            requester_name=(requester_name or "").strip(), contact_email=(contact_email or "").strip(),
            contact_phone=(contact_phone or "").strip(), title=(title or "").strip(),
            description=(description or "").strip(), source_link=(source_link or "").strip(),
            capability_payload=capability_payload or {}, assigned_machine=assigned,
        )
        _audit_transition(actor, service_request, "submitted")
        _notify_after_commit(service_request, "submitted")
        return service_request


def accept(service_request, actor, *, estimated_minutes=None, planned_grams=None, note=""):
    with transaction.atomic():
        _assert_request_write_allowed(service_request)
        locked = _locked_request(service_request)
        _require_module(locked.makerspace)
        _require_edge(locked, MachineServiceRequest.Status.ACCEPTED)
        if estimated_minutes is not None:
            locked.estimated_minutes = _minutes(estimated_minutes, "estimated_minutes")
        if planned_grams is not None:
            grams = _decimal(planned_grams, "planned_grams")
            if grams < 0:
                raise ServiceConsumptionInvalid("planned_grams must be non-negative.")
            locked.planned_grams = grams
            payload = dict(locked.capability_payload or {})
            if grams:
                payload["estimated_grams"] = str(grams)
            else:
                payload.pop("estimated_grams", None)
            locked.capability_payload = payload
        if note:
            locked.reason = str(note).strip()
        locked.status, locked.handled_by, locked.accepted_by, locked.accepted_at = MachineServiceRequest.Status.ACCEPTED, actor, actor, timezone.now()
        locked.save(update_fields=["status", "handled_by", "accepted_by", "accepted_at", "estimated_minutes", "planned_grams", "capability_payload", "reason", "updated_at"])
        _audit_transition(actor, locked, "accepted")
        _notify_after_commit(locked, "accepted")
        return locked


def reject(service_request, actor, *, reason):
    with transaction.atomic():
        _assert_request_write_allowed(service_request)
        if not str(reason or "").strip():
            raise ServiceConsumptionInvalid("A rejection reason is required.")
        locked = _locked_request(service_request)
        _require_module(locked.makerspace)
        _require_edge(locked, MachineServiceRequest.Status.REJECTED)
        locked.status, locked.handled_by, locked.reason = MachineServiceRequest.Status.REJECTED, actor, str(reason).strip()
        locked.save(update_fields=["status", "handled_by", "reason", "updated_at"])
        _audit_transition(actor, locked, "rejected")
        _notify_after_commit(locked, "rejected")
        return locked


def start(service_request, actor, machine_scope, *, machine_id=None, estimated_minutes=None, consumable_pool_id=None, planned_grams=None, planned_quantity=None):
    with transaction.atomic():
        _assert_request_write_allowed(service_request)
        locked = _locked_request(service_request)
        _require_module(locked.makerspace)
        _require_edge(locked, MachineServiceRequest.Status.IN_PROGRESS)
        queue = None
        if locked.queue_id:
            queue = ServiceQueue.objects.select_for_update().select_related("makerspace", "machine_type").get(pk=locked.queue_id)
            locked.queue = queue
        candidate_scope = role_scope.scope_q_for(
            machine_scope,
            machine_id_paths=("pk",),
            type_id_paths=("machine_type_id",),
        )
        if machine_id is None and queue and queue.allocation_policy == ServiceQueue.AllocationPolicy.FIRST_IDLE:
            machine = Machine.objects.select_for_update().select_related("makerspace", "machine_type").filter(
                candidate_scope,
                makerspace_id=locked.makerspace_id, machine_type_id=queue.machine_type_id,
                is_active=True, status=Machine.Status.IDLE,
            ).order_by("id").first()
        elif machine_id is None:
            raise ServiceMachineUnavailable("A machine is required to start service.")
        else:
            machine = Machine.objects.select_for_update().select_related("makerspace", "machine_type").filter(
                candidate_scope,
                pk=machine_id,
            ).first()
        if machine is None or machine.makerspace_id != locked.makerspace_id:
            raise ServiceMachineUnavailable("Machine is not available for this service request.")
        if locked.queue_id and machine.machine_type_id != queue.machine_type_id:
            raise ServiceMachineUnavailable("Machine is not compatible with this service queue.")
        _require_available(machine)
        if locked.queue_id and queue.capacity is not None:
            active = MachineServiceRequest.objects.select_for_update().filter(queue=locked.queue, status=MachineServiceRequest.Status.IN_PROGRESS).count()
            if active >= queue.capacity:
                raise ServiceMachineUnavailable("Service queue capacity has been reached.")
        if estimated_minutes is not None:
            locked.estimated_minutes = _minutes(estimated_minutes, "estimated_minutes")
        _require_printer_start_inputs(locked, machine, consumable_pool_id, planned_grams)
        if consumable_pool_id is not None or planned_grams is not None or planned_quantity is not None:
            if consumable_pool_id is None or (planned_grams is None) == (planned_quantity is None):
                raise ServiceConsumptionInvalid("A consumable pool and exactly one planned quantity must be supplied together.")
            from apps.machines.models import MachineConsumablePool
            from apps.machines.service_consumable_pools import reserve_for_request
            reserve_for_request(locked, actor, pool=MachineConsumablePool.objects.get(pk=consumable_pool_id),
                                planned_grams=planned_grams, planned_quantity=planned_quantity, machine=machine)
            locked.refresh_from_db()
        locked.assigned_machine, locked.status, locked.handled_by, locked.started_at = machine, MachineServiceRequest.Status.IN_PROGRESS, actor, timezone.now()
        locked.run_machine_name = machine.name
        locked.run_machine_model = str((machine.type_payload or {}).get("model", ""))
        locked.run_estimated_minutes = locked.estimated_minutes
        locked.run_planned_grams = locked.planned_grams
        if locked.run_consumable_pool_id:
            pool = locked.run_consumable_pool
            locked.run_consumable_label, locked.run_consumable_material, locked.run_consumable_color = pool.label, pool.material, pool.color
        locked.save(update_fields=["assigned_machine", "status", "handled_by", "started_at", "estimated_minutes", "run_machine_name", "run_machine_model", "run_consumable_label", "run_consumable_material", "run_consumable_color", "run_estimated_minutes", "run_planned_grams", "updated_at"])
        machine.status = Machine.Status.RUNNING
        machine.save(update_fields=["status", "updated_at"])
        _audit_transition(actor, locked, "assigned", extra={"machine_id": machine.pk})
        _audit_transition(actor, locked, "started")
        _notify_after_commit(locked, "started")
        return locked


def complete(service_request, actor, *, actual_minutes, consumptions, actual_grams=None, actual_quantity=None):
    with transaction.atomic():
        _assert_request_write_allowed(service_request)
        locked = _locked_request(service_request)
        _require_module(locked.makerspace)
        _require_edge(locked, MachineServiceRequest.Status.COMPLETED)
        _lock_assigned_machine(locked)
        locked.actual_minutes = _minutes(actual_minutes, "actual_minutes")
        debit_consumptions(locked, actor, consumptions, outcome="completed")
        if locked.run_consumable_pool_id:
            from apps.machines.service_consumable_pools import reconcile_request
            reconcile_request(locked, actor, actual_grams=locked.planned_grams if actual_grams is None else actual_grams,
                              actual_quantity=actual_quantity)
            locked.refresh_from_db()
            locked.actual_minutes = _minutes(actual_minutes, "actual_minutes")
        locked.status, locked.handled_by, locked.completed_at = MachineServiceRequest.Status.COMPLETED, actor, timezone.now()
        locked.save(update_fields=["status", "handled_by", "actual_minutes", "completed_at", "updated_at"])
        _release_queue_machine(locked)
        _audit_transition(actor, locked, "completed")
        _notify_after_commit(locked, "completed")
        from apps.machines.service_payments import create_for_completed_request
        create_for_completed_request(locked, actor)
        return locked


def fail(service_request, actor, *, reason, percent_complete, actual_minutes, consumptions, actual_grams=None, actual_quantity=None):
    with transaction.atomic():
        _assert_request_write_allowed(service_request)
        if not str(reason or "").strip():
            raise ServiceConsumptionInvalid("A failure reason is required.")
        locked = _locked_request(service_request)
        _require_module(locked.makerspace)
        _require_edge(locked, MachineServiceRequest.Status.FAILED)
        _lock_assigned_machine(locked)
        locked.actual_minutes, locked.fail_percent_complete, locked.reason, locked.failed_at = _minutes(actual_minutes, "actual_minutes"), _percent(percent_complete), str(reason).strip(), timezone.now()
        debit_consumptions(locked, actor, consumptions, outcome="failed")
        if locked.run_consumable_pool_id:
            from apps.machines.service_consumable_pools import reconcile_request
            if locked.reserved_quantity is not None and locked.metering_unit != "weight":
                expected_quantity = locked.reserved_quantity * locked.fail_percent_complete / 100
                reconcile_request(locked, actor,
                                  actual_quantity=expected_quantity if actual_quantity is None else actual_quantity,
                                  reason=locked.reason)
            else:
                expected = locked.planned_grams * locked.fail_percent_complete / 100
                reconcile_request(locked, actor, actual_grams=expected if actual_grams is None else actual_grams,
                                  reason=locked.reason)
            locked.refresh_from_db()
            locked.actual_minutes = _minutes(actual_minutes, "actual_minutes")
            locked.fail_percent_complete = _percent(percent_complete)
            locked.reason = str(reason).strip()
            locked.failed_at = timezone.now()
        locked.status, locked.handled_by = MachineServiceRequest.Status.FAILED, actor
        locked.save(update_fields=["status", "handled_by", "actual_minutes", "fail_percent_complete", "reason", "failed_at", "updated_at"])
        _release_queue_machine(locked)
        _audit_transition(actor, locked, "failed")
        _notify_after_commit(locked, "failed")
        return locked


def collect(service_request, actor):
    with transaction.atomic():
        _assert_request_write_allowed(service_request)
        locked = _locked_request(service_request)
        _require_module(locked.makerspace)
        _require_edge(locked, MachineServiceRequest.Status.COLLECTED)
        locked.status, locked.handled_by, locked.collected_by, locked.collected_at = MachineServiceRequest.Status.COLLECTED, actor, actor, timezone.now()
        locked.save(update_fields=["status", "handled_by", "collected_by", "collected_at", "updated_at"])
        _audit_transition(actor, locked, "collected")
        _notify_after_commit(locked, "collected")
        return locked


def create_reprint(service_request, actor):
    """Create an accepted child request that retains the original attachment root."""
    with transaction.atomic():
        _assert_request_write_allowed(service_request)
        original = _locked_request(service_request)
        if original.status not in {MachineServiceRequest.Status.FAILED, MachineServiceRequest.Status.COMPLETED, MachineServiceRequest.Status.COLLECTED}:
            raise ServiceInvalidTransition("Only terminal service requests can be reprinted.")
        root = original.reprint_of or original
        child = MachineServiceRequest.objects.create(
            bucket=original.bucket, queue=original.queue, makerspace=original.makerspace, requester=original.requester, member=original.member,
            requester_name=original.requester_name, contact_email=original.contact_email, contact_phone=original.contact_phone,
            title=original.title, description=original.description, source_link=original.source_link,
            capability_payload=original.capability_payload, status=MachineServiceRequest.Status.ACCEPTED,
            assigned_machine=original.assigned_machine if original.bucket_id else None, accepted_by=actor,
            accepted_at=timezone.now(), estimated_minutes=original.estimated_minutes, planned_grams=original.planned_grams,
            reprint_of=root,
        )
        _audit_transition(actor, child, "reprint_created", extra={"reprint_of_id": root.pk})
        return child


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
