"""Kernel-only public printer-service contract."""

from decimal import Decimal
import json

from django.db import transaction
from django.db.models import Q
from rest_framework.exceptions import NotFound, ValidationError

from apps.machines.metering import ConsumablePoolUnit
from apps.machines.models import (
    MachineConsumablePool,
    MachineServiceRequest,
    ServiceQueue,
    ServiceRequestFile,
)
from apps.machines.print_uploads import validate_print_upload

from apps.machines.printer_capabilities import resolve_global_printer_type
from apps.machines.service_queue_position import queue_counts_for
from apps.machines.service_storage import create_staged_queue_file, finalize_file
from apps.machines.service_workflow import submit
from apps.makerspaces import limits
from apps.makerspaces.servability import servable_queryset


def _kernel_queues(makerspace):
    printer_type = resolve_global_printer_type()
    if printer_type is None:
        return ServiceQueue.objects.none()
    return ServiceQueue.objects.filter(
        makerspace=makerspace,
        is_active=True,
        machine_type=printer_type,
    )


def public_queues(makerspace):
    return _kernel_queues(makerspace).order_by("name", "id")


def _eligible_public_pools(makerspace):
    printer_type = resolve_global_printer_type()
    if printer_type is None:
        return MachineConsumablePool.objects.none()
    serves_printers = (
        Q(machine_type=printer_type)
        | Q(machine__machine_type=printer_type)
        | Q(machine__isnull=True, machine_type__isnull=True)
    )
    return MachineConsumablePool.objects.filter(
        serves_printers,
        makerspace=makerspace,
        is_active=True,
        is_public=True,
        remaining_grams__gt=0,
        unit=ConsumablePoolUnit.GRAMS,
    )


def public_pools(makerspace):
    return _eligible_public_pools(makerspace).order_by("material", "color", "id")


def resolve_queue(makerspace, queue_id, *, compatibility=False):
    """Resolve an active public queue; canonical requests never create a queue."""
    rows = _kernel_queues(makerspace)
    if compatibility:
        row = rows.filter(legacy_print_bucket_id=queue_id).first() if queue_id is not None else rows.filter(name="Public Requests").first()
    elif queue_id is not None:
        row = rows.filter(pk=queue_id).first()
    else:
        choices = list(rows[:2])
        row = choices[0] if len(choices) == 1 else None
    if row is None:
        raise ValidationError({"queue_id": "Select an active public printer queue."})
    return row


def stage_upload(makerspace, data, actor, *, compatibility=False, legacy_presigner=None):
    queue = resolve_queue(makerspace, data.get("queue_id"), compatibility=compatibility)
    try:
        content_type = validate_print_upload(data["kind"], data["filename"], data.get("content_type", ""))
    except ValueError as exc:
        raise ValidationError({"file": str(exc)}) from exc
    upload, presigned = create_staged_queue_file(
        queue, actor=actor, filename=data["filename"], content_type=content_type,
        kind="model" if data["kind"] == "stl" else "screenshot",
    )
    return {"file_id": upload.id, "upload": presigned}

def _settings(value):
    if value in (None, ""):
        return None
    if isinstance(value, dict):
        return value
    try:
        value = json.loads(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError({"preferred_settings": "Printer preferred settings must be an object."}) from exc
    if not isinstance(value, dict):
        raise ValidationError({"preferred_settings": "Printer preferred settings must be an object."})
    return value


def _kernel_payload(queue, data):
    pool = None
    if data.get("consumable_pool_id") is not None:
        pool = _eligible_public_pools(queue.makerspace).filter(
            pk=data["consumable_pool_id"]
        ).first()
        if pool is None:
            raise ValidationError({"consumable_pool_id": "Invalid or inactive consumable pool."})
    config = queue.machine_type.capability_config
    material, color = data.get("material", ""), data.get("color", "")
    if pool:
        material, color = material or pool.material, color or pool.color
    no_preference = pool is None and not material and not color
    payload = {"requested_material": material or config["accepted_materials"][0], "requested_color": color or config["accepted_colours"][0], "quantity": data.get("quantity", 1), "project_brief": data.get("project_brief", "")}
    if no_preference:
        payload["no_filament_preference"] = True
    if data.get("estimated_filament_grams") not in (None, Decimal("0"), 0):
        payload["estimated_grams"] = str(data["estimated_filament_grams"])
    if pool:
        payload["requested_consumable_pool"] = pool.pk
    if (settings := _settings(data.get("preferred_settings"))) is not None:
        payload["preferred_settings"] = settings
    return payload


def submit_request(makerspace, data, actor, *, compatibility=False):
    """Submit a kernel request and charge print quota exactly once."""
    queue = resolve_queue(makerspace, data.get("queue_id"), compatibility=compatibility)
    with transaction.atomic():
        limits.check_quota(makerspace, "print", adding=1)
        row = submit(queue, actor, member=actor, actor=actor, requester_name=actor.display_name or "", contact_email=actor.email or "", contact_phone=actor.phone or "", title=data["title"], description=data.get("description", ""), source_link=data.get("source_link", ""), capability_payload=_kernel_payload(queue, data))
        ids = data.get("file_ids") or []
        files = list(ServiceRequestFile.objects.select_for_update().filter(id__in=ids, makerspace=makerspace, queue=queue, owner_user_id=actor.pk, service_request__isnull=True, attached_at__isnull=True))
        if len(files) != len(set(ids)):
            raise ValidationError({"file_ids": "One or more uploads are invalid, already used, or not yours."})
        for file in files:
            finalize_file(row, file_id=file.pk, actor=actor)
        return row


class _StatusProjection:
    def __init__(self, row):
        self.id = row.pk
        self.public_token = row.public_token
        self.status = "printing" if row.status == MachineServiceRequest.Status.IN_PROGRESS else row.status
        self.title, self.created_at = row.title, row.created_at
        self.accepted_at, self.started_at, self.completed_at = row.accepted_at, row.started_at, row.completed_at
        self.estimated_minutes = row.estimated_minutes


def public_status(public_token):
    """Return a PII-free printer-status projection or 404."""
    printer_type = resolve_global_printer_type()
    if printer_type is None:
        raise NotFound()
    # Identity comes from the resolved global printer type rather than a slug, and
    # tenancy stays routed through the servability policy rather than a raw
    # archived_at filter.
    kernel = servable_queryset(MachineServiceRequest.objects.select_related("makerspace").filter(
        public_token=public_token,
        queue__machine_type=printer_type,
    ), relation="makerspace").first()
    if kernel is None:
        raise NotFound()
    return _StatusProjection(kernel), queue_counts_for([kernel])
