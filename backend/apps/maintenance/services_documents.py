from django.db import transaction
from rest_framework.exceptions import ValidationError

from apps.audit.services import record
from apps.accounts import rbac
from apps.machines.models import MachineDocument
from apps.makerspaces import limits
from apps.maintenance import storage
from apps.maintenance.models import MaintenanceLog, MaintenanceLogDocument
from apps.maintenance.services_shared import lock_machine, prepare_machine


@transaction.atomic
def finalize_log_document(log, *, actor, object_key):
    machine = lock_machine(log.machine, actor)
    prepare_machine(machine, actor, manage=False)
    log = rbac.scope_by_makerspace(
        actor, MaintenanceLog.objects.select_for_update(), makerspace_field="machine__makerspace_id",
    ).get(
        pk=log.pk, machine=machine,
    )
    storage.assert_log_document_object_key(
        object_key, machine.makerspace_id, machine.pk,
    )
    if (
        MaintenanceLogDocument.objects.filter(object_key=object_key).exists()
        or MachineDocument.objects.filter(object_key=object_key).exists()
    ):
        raise ValidationError({"object_key": "This document is already attached."})

    try:
        storage.finalize_upload(object_key)
        result = storage.validate_log_document_object(object_key)
        limits.add_storage(machine.makerspace, result.size)
        document = MaintenanceLogDocument.objects.create(
            log=log,
            object_key=object_key,
            size_bytes=result.size,
            uploaded_by=actor,
        )
        record(
            actor,
            "maintenance.document_added",
            makerspace=machine.makerspace,
            target=document,
            meta={"log_id": log.pk, "machine_id": machine.pk, "size_bytes": result.size},
        )
    except Exception:
        storage.cleanup_upload(object_key)
        raise
    return document


@transaction.atomic
def delete_log_document(document, *, actor):
    machine = lock_machine(document.log.machine, actor)
    prepare_machine(machine, actor, manage=True)
    log = rbac.scope_by_makerspace(
        actor, MaintenanceLog.objects.select_for_update(), makerspace_field="machine__makerspace_id",
    ).get(
        pk=document.log_id, machine=machine,
    )
    document = rbac.scope_by_makerspace(
        actor, MaintenanceLogDocument.objects.select_for_update(), makerspace_field="log__machine__makerspace_id",
    ).get(
        pk=document.pk, log=log,
    )
    object_key = document.object_key
    size_bytes = document.size_bytes
    document_id = document.pk
    record(
        actor,
        "maintenance.document_deleted",
        makerspace=machine.makerspace,
        target=document,
        meta={
            "document_id": document_id,
            "log_id": log.pk,
            "machine_id": machine.pk,
            "size_bytes": size_bytes,
        },
    )
    document.delete()
    limits.free_storage(machine.makerspace, size_bytes)
    storage.delete_object(object_key)
