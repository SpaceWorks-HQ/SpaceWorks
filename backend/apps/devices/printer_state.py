"""Advisory staff state; public APIs continue exposing authoritative Machine.status."""
from django.utils import timezone


def effective_printer_state(machine, device, job=None, *, request_in_progress=False, now=None):
    now = now or timezone.now()
    if machine.status in {"maintenance", "reserved", "offline"}:
        return machine.status
    if device.status != "active" or device.last_seen_at is None or (now - device.last_seen_at).total_seconds() > device.offline_threshold_seconds:
        return "device_offline"
    if machine.status == "running" or request_in_progress:
        return "running"
    fresh = job is not None and job.telemetry_at is not None and (now - job.telemetry_at).total_seconds() <= device.offline_threshold_seconds
    if machine.status == "idle" and fresh and job.telemetry_state == "running" and job.state == "awaiting":
        return "running"
    return machine.status
