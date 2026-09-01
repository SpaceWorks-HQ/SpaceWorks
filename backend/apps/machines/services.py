"""Audited workflow services for machine mutations."""
from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.audit.services import record
from apps.inventory import public_image_storage
from apps.machines import access, storage
from apps.machines.models import (
    Machine, MachineDocument, MachineErrorLog, MachineOperator, MachineUsageEntry,
)
from apps.makerspaces import limits
from apps.makerspaces.guards import require_module_locked


def _retired(machine):
    if not machine.is_active:
        raise ValidationError("Machine is retired.")


def _audit(machine, actor, action, meta=None):
    return record(
        actor, action, makerspace=machine.makerspace, target=machine,
        target_type="machine", meta=meta or {},
    )


@transaction.atomic
def set_status(machine, actor, status):
    if status not in Machine.Status.values:
        raise ValidationError({"status": "Invalid machine status."})
    _retired(machine)
    machine = Machine.objects.select_for_update().get(pk=machine.pk)
    _retired(machine)
    old_status = machine.status
    machine.status = status
    machine.save(update_fields=["status", "updated_at"])
    _audit(machine, actor, "machine.status_changed", {"old": old_status, "new": status})
    return machine


@transaction.atomic
def log_usage(machine, actor, hours, note=""):
    _retired(machine)
    if hours <= 0:
        raise ValidationError({"hours": "Hours must be greater than zero."})
    machine = Machine.objects.select_for_update().get(pk=machine.pk)
    _retired(machine)
    entry = MachineUsageEntry.objects.create(
        machine=machine,
        hours=hours,
        source=MachineUsageEntry.Source.MANUAL,
        note=note,
        logged_by=actor,
    )
    _audit(machine, actor, "machine.usage_logged", {"hours": str(hours), "note": note})
    return entry


def machine_usage_total(machine):
    return machine.usage_entries.aggregate(total=Sum("hours"))["total"] or Decimal("0")


@transaction.atomic
def update_image(machine, actor, object_key):
    # No tenant-wide lock: a `machine/` key is pinned to that prefix by the attach view,
    # so only another Machine can claim it and this row lock is what serializes that.
    machine = Machine.objects.select_for_update().select_related("makerspace").get(
        pk=machine.pk
    )
    old_key = machine.image_key
    if object_key and object_key != old_key and public_image_storage.public_image_key_in_use(
        machine.makerspace_id,
        object_key,
        machine_id=machine.pk,
    ):
        raise ValidationError({"object_key": "This image is already in use."})
    if old_key and old_key != object_key:
        public_image_storage.release_public_image_on_commit(
            machine.makerspace, old_key
        )
    machine.image_key = object_key
    machine.save(update_fields=["image_key", "updated_at"])
    _audit(machine, actor, "machine.image_updated")
    return machine


@transaction.atomic
def remove_image(machine, actor):
    machine = Machine.objects.select_for_update().select_related("makerspace").get(
        pk=machine.pk
    )
    if machine.image_key:
        public_image_storage.release_public_image_on_commit(
            machine.makerspace, machine.image_key
        )
    machine.image_key = ""
    machine.save(update_fields=["image_key", "updated_at"])
    _audit(machine, actor, "machine.image_removed")
    return machine


@transaction.atomic
def assign_operator(machine, actor, user, access_level):
    _retired(machine)
    if access_level not in MachineOperator.AccessLevel.values:
        raise ValidationError({"access_level": "Invalid operator access level."})
    machine = Machine.objects.select_for_update().get(pk=machine.pk)
    _retired(machine)
    if not access.is_active_member(user, machine.makerspace_id):
        raise ValidationError({"user": "User is not an active makerspace member."})
    existing = MachineOperator.objects.filter(machine=machine, user=user).first()
    existing_level = existing.access_level if existing else None
    if not access.can_assign_operator(
        actor,
        machine,
        target_level=access_level,
        existing_level=existing_level,
    ):
        raise PermissionDenied()
    row, created = MachineOperator.objects.update_or_create(
        machine=machine,
        user=user,
        defaults={"access_level": access_level, "assigned_by": actor},
    )
    action = "machine.operator_assigned" if created else "machine.operator_updated"
    _audit(
        machine,
        actor,
        action,
        {"user_id": user.pk, "access_level": access_level, "old_access_level": existing_level},
    )
    return row


@transaction.atomic
def remove_operator(machine, actor, user):
    _retired(machine)
    row = MachineOperator.objects.filter(machine=machine, user=user).first()
    if row is None:
        return
    if not access.can_assign_operator(
        actor,
        machine,
        target_level=row.access_level,
        existing_level=row.access_level,
    ):
        raise PermissionDenied()
    access_level = row.access_level
    row.delete()
    _audit(
        machine,
        actor,
        "machine.operator_removed",
        {"user_id": user.pk, "access_level": access_level},
    )


@transaction.atomic
def retire_machine(machine, actor):
    if not access.can_retire_machine(actor, machine):
        raise PermissionDenied()
    machine = Machine.objects.select_for_update().get(pk=machine.pk)
    old_status = machine.status
    machine.is_active = False
    machine.status = Machine.Status.OFFLINE
    machine.save(update_fields=["is_active", "status", "updated_at"])
    _audit(machine, actor, "machine.retired", {"old_status": old_status})
    return machine


@transaction.atomic
def unretire_machine(machine, actor):
    if not access.can_unretire_machine(actor, machine):
        raise PermissionDenied()
    machine = Machine.objects.select_for_update().get(pk=machine.pk)
    require_module_locked(machine.makerspace, "machines")
    limits.check_quota(machine.makerspace, "machines", adding=1)
    machine.is_active = True
    machine.save(update_fields=["is_active", "updated_at"])
    _audit(machine, actor, "machine.unretired")
    return machine


@transaction.atomic
def log_error(machine, actor, severity, message):
    _retired(machine)
    if severity not in MachineErrorLog.Severity.values:
        raise ValidationError({"severity": "Invalid error severity."})
    machine = Machine.objects.select_for_update().get(pk=machine.pk)
    _retired(machine)
    row = MachineErrorLog.objects.create(
        machine=machine,
        severity=severity,
        message=message,
        logged_by=actor,
    )
    _audit(machine, actor, "machine.error_logged", {"severity": severity})
    return row


@transaction.atomic
def attach_document(machine, actor, object_key, doc_type, original_filename):
    if doc_type not in MachineDocument.DocType.values:
        raise ValidationError({"doc_type": "Invalid machine document type."})
    storage.assert_machine_object_key_for_makerspace(object_key, machine.makerspace_id)
    if MachineDocument.objects.filter(object_key=object_key).exists():
        raise ValidationError("Evidence already used.")
    from django.conf import settings

    storage.finalize_upload(object_key, settings.MACHINE_DOC_MAX_BYTES)
    result = storage.validate_machine_object(object_key)
    doc = MachineDocument.objects.create(
        machine=machine,
        doc_type=doc_type,
        object_key=object_key,
        original_filename=original_filename,
        content_type=result.content_type,
        size_bytes=result.size,
        uploaded_by=actor,
    )
    _audit(
        machine,
        actor,
        "machine.document_added",
        {"document_id": doc.pk, "doc_type": doc_type, "object_key": object_key},
    )
    return doc


@transaction.atomic
def remove_document(machine, actor, document):
    object_key = document.object_key
    document_id = document.pk
    document.delete()
    storage.delete_object(object_key)
    _audit(
        machine,
        actor,
        "machine.document_removed",
        {"document_id": document_id, "object_key": object_key},
    )
