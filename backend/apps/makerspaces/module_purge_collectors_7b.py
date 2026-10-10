"""Commands and printer history belong to devices; adapter purges only null live edges."""
from apps.makerspaces.module_purge_collectors_single_model import _delete


def delete_printer_rows(makerspace):
    from apps.devices.models import DeviceCommand, PrinterDeviceBinding, PrinterJob, PrinterJobConsumption
    labels = set()
    counts = {}
    for model, key, filter_args in (
        (PrinterJobConsumption, "printer_consumptions", {"job__makerspace": makerspace}),
        (PrinterJob, "printer_jobs", {"makerspace": makerspace}),
        (DeviceCommand, "device_commands", {"makerspace": makerspace}),
        (PrinterDeviceBinding, "printer_bindings", {"makerspace": makerspace}),
    ):
        count, deleted_labels = _delete(model.objects.filter(**filter_args))
        labels |= deleted_labels
        counts[key] = count
    return counts, labels
