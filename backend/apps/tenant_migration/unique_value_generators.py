"""Collision handlers and target-key generators for tenant materialization."""

from pathlib import PurePosixPath


def _extension(value):
    suffix = PurePosixPath(str(value)).name
    return suffix.rsplit(".", 1)[1] if "." in suffix else ""


def _refuses_collision(handler):
    """Mark a handler that stops the import instead of minting a replacement value.

    A collision on one of these identities cannot happen between two deployments that
    pairing would allow to trade a tenant, so reaching one means an assumption broke.
    The marker lets a caller enumerate them without matching on function names.
    """
    handler.refuses_collision = True
    return handler


def evidence_key(row, target, _source_value):
    from apps.evidence.storage import evidence_object_key

    return evidence_object_key(target.pk, row["evidence_type"])


def certificate_key(row, target, _source_value):
    return f"event-certificates/{target.pk}/{row['serial']}.pdf"


@_refuses_collision
def refuse_certificate_serial_collision(row, target, source_value):
    raise RuntimeError(
        "An attendance-certificate serial collision cannot be regenerated because "
        "the serial is printed inside the immutable PDF."
    )


@_refuses_collision
def refuse_checkin_operation_collision(row, target, source_value):
    raise RuntimeError(
        "An immutable check-in operation UUID collision cannot be regenerated without "
        "breaking its audit provenance."
    )


def machine_document_key(row, target, source_value):
    from apps.machines.storage import machine_object_key

    return machine_object_key(target.pk, _extension(source_value))


def service_file_key(row, target, _source_value):
    from apps.machines.service_storage import service_object_key

    context = row.get("service_request_id") or row.get("queue_id") or row["id"]
    return service_object_key(target.pk, context)


def maintenance_document_key(row, target, source_value):
    from apps.maintenance.models import MaintenanceLog
    from apps.maintenance.storage import log_document_object_key

    machine_id = MaintenanceLog.objects.values_list("machine_id", flat=True).get(
        pk=row["log_id"]
    )
    return log_document_object_key(target.pk, machine_id, _extension(source_value))


def receipt_key(row, target, source_value):
    from apps.procurement.storage import receipt_object_key

    return receipt_object_key(target.pk, _extension(source_value))


def warranty_document_key(row, target, source_value):
    from apps.warranty.storage import warranty_object_key

    return warranty_object_key(target.pk, _extension(source_value))
