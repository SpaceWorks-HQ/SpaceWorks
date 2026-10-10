"""Label adapter scope and lock order: tenant -> device -> command -> label -> batch."""
from django.shortcuts import get_object_or_404
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.accounts import rbac
from apps.devices.errors_labels import LabelConflict
from apps.devices.models import Device, LabelPrintCommand
from apps.devices.services_locks import lock_tenant
from apps.makerspaces.platform import module_enabled
from apps.makerspaces.guards import require_module
from apps.operations.models import QrPrintBatch

MODULES = ("devices", "qr_print_batches")


def require_adapter(makerspace_id):
    for key in MODULES:
        require_module(makerspace_id, key)


def authorize_staff(actor, makerspace_id):
    require_adapter(makerspace_id)
    if not rbac.can(actor, rbac.Action.MANAGE_QR, makerspace_id):
        raise PermissionDenied()


def scoped_batches(actor):
    return rbac.scope_by_action(actor, rbac.Action.MANAGE_QR, QrPrintBatch.objects.all())


def locked_label_device(principal):
    makerspace = lock_tenant(principal.makerspace_id)
    require_adapter(makerspace.pk)
    device = get_object_or_404(Device.objects.select_for_update(),
                               pk=principal.device_id, makerspace=makerspace)
    if (device.kind != Device.Kind.LABEL_PRINTER or device.status != Device.Status.ACTIVE
            or device.key_version != principal.key_version):
        raise PermissionDenied("Device authorization is no longer active.")
    return makerspace, device


def owned_label(device, label_id):
    from apps.devices.models_commands import DeviceCommand

    identity = get_object_or_404(LabelPrintCommand.objects.filter(device=device,
        makerspace_id=device.makerspace_id).values("command_id"), pk=label_id)
    command = get_object_or_404(DeviceCommand.objects.select_for_update(),
        pk=identity["command_id"], device=device, makerspace_id=device.makerspace_id)
    label = LabelPrintCommand.objects.select_for_update().get(pk=label_id)
    if command.device_key_version != device.key_version:
        raise PermissionDenied("Command belongs to a previous device key.")
    if command.status != DeviceCommand.Status.ACKNOWLEDGED or command.kind != "label_print":
        raise LabelConflict("Command must be acknowledged and not cancelled.")
    return label, command


def delivery_target(makerspace, device, command):
    """Return None for generic polling; caller commits cancellation, not a 400 rollback."""
    label = LabelPrintCommand.objects.select_for_update().filter(
        command=command, device=device, makerspace=makerspace).first()
    if (label is None or device.kind != Device.Kind.LABEL_PRINTER
            or command.device_key_version != device.key_version
            or label.result in [LabelPrintCommand.Result.SUCCEEDED, LabelPrintCommand.Result.FAILED]
            or not all(module_enabled(makerspace, key) for key in MODULES)):
        return None
    batch = QrPrintBatch.objects.select_for_update().filter(pk=label.batch_id,
        makerspace=makerspace, status=QrPrintBatch.Status.PRINTED).first()
    return label if batch is not None else None


def locked_batch(label, device):
    batch = QrPrintBatch.objects.select_for_update().filter(
        pk=label.batch_id, makerspace_id=device.makerspace_id,
        status=QrPrintBatch.Status.PRINTED).first()
    if batch is not None and batch.items.count() != label.item_count_snapshot:
        raise ValidationError("Label batch contents changed.")
    return batch
