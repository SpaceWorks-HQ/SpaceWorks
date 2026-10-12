"""Staff send/reprint: DB-backed idempotency and first-send batch freeze."""
from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework.exceptions import ValidationError

from apps.accounts import rbac
from apps.devices.errors_labels import LabelConflict
from apps.devices.label_access import authorize_staff, scoped_batches
from apps.devices.models import Device, LabelPrintCommand
from apps.devices.services_label_events import record
from apps.devices.services_locks import lock_tenant
from apps.operations.models import QrPrintBatch
from apps.operations.services_qr_assets import mark_batch_printed


def create_label_command(actor, batch_id, *, device_id, request_id):
    from apps.devices.models_commands import DeviceCommand

    identity = get_object_or_404(scoped_batches(actor).values("makerspace_id"), pk=batch_id)
    with transaction.atomic():
        makerspace = lock_tenant(identity["makerspace_id"])
        authorize_staff(actor, makerspace.pk)
        devices = rbac.scope_by_action(actor, rbac.Action.MANAGE_QR, Device.objects.all())
        device = get_object_or_404(devices.select_for_update(), pk=device_id, makerspace=makerspace)
        batch = get_object_or_404(scoped_batches(actor).select_for_update(), pk=batch_id,
                                  makerspace=makerspace)
        if device.kind != Device.Kind.LABEL_PRINTER or device.status != Device.Status.ACTIVE:
            raise ValidationError("An active label printer is required.")
        previous = rbac.scope_by_action(actor, rbac.Action.MANAGE_QR,
            LabelPrintCommand.objects.all()).filter(makerspace=makerspace, request_id=request_id).first()
        if previous is not None:
            if previous.device_id != device.pk or previous.batch_id != batch.pk:
                raise LabelConflict("Request ID has already been used for another payload.")
            return previous, False
        if batch.status == QrPrintBatch.Status.ARCHIVED:
            raise ValidationError("Archived QR batches cannot be sent.")
        count = batch.items.count()
        if count == 0:
            raise ValidationError("A label batch must contain at least one item.")
        command = DeviceCommand.objects.create(makerspace=makerspace, device=device,
            device_key_version=device.key_version, kind="label_print", created_by=actor)
        label = LabelPrintCommand.objects.create(command=command, makerspace=makerspace,
            device=device, batch=batch, request_id=request_id, requested_by=actor,
            batch_id_snapshot=batch.pk, batch_title_snapshot=batch.title, item_count_snapshot=count)
        if batch.status == QrPrintBatch.Status.DRAFT:
            mark_batch_printed(actor, batch)
        record(makerspace, device, "label_command_created", label, command, actor=actor)
    return label, True
