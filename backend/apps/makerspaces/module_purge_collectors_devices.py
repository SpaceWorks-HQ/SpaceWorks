"""Devices-module purge: authentication rows first, then identity and its history.

Runs inside the authorized purge context, so the DeviceEvent append-only trigger admits
the DELETE. Enrollments and replay nonces go before the Device rows they authenticate,
so no instant exists where a device survives without its revocation path. The module
stores no object-storage keys. Printer failure notes are scoped PII without a blind index.
"""
from apps.makerspaces.module_purge_collectors_single_model import _counts, _delete


def devices_delete(makerspace, cursor):
    from apps.devices.models import Device, DeviceEnrollment, DeviceEvent, DeviceRequestNonce

    from .module_purge_collectors_7b import delete_printer_rows

    printer_counts, printer_labels = delete_printer_rows(makerspace)
    nonces, nonce_labels = _delete(DeviceRequestNonce.objects.filter(device__makerspace=makerspace))
    enrollments, enrollment_labels = _delete(DeviceEnrollment.objects.filter(makerspace=makerspace))
    events, event_labels = _delete(DeviceEvent.objects.filter(makerspace=makerspace))
    devices, device_labels = _delete(Device.objects.filter(makerspace=makerspace))
    return _counts(
        model_labels=printer_labels | nonce_labels | enrollment_labels | event_labels | device_labels,
        **printer_counts,
        device_nonces=nonces,
        device_enrollments=enrollments,
        device_events=events,
        devices=devices,
    )
