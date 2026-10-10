from datetime import timedelta
from types import SimpleNamespace as Row

import pytest
from django.utils import timezone

from apps.devices.printer_state import effective_printer_state


@pytest.mark.parametrize("machine_status,device_status,stale,telemetry,request_running,expected", [
    ("maintenance", "revoked", True, "running", True, "maintenance"),
    ("reserved", "active", False, "running", True, "reserved"),
    ("offline", "active", False, "running", True, "offline"),
    ("running", "revoked", False, "running", True, "device_offline"),
    ("idle", "active", True, "running", False, "device_offline"),
    ("running", "active", False, "idle", False, "running"),
    ("idle", "active", False, "idle", True, "running"),
    ("idle", "active", False, "running", False, "running"),
    ("idle", "active", False, "idle", False, "idle"),
])
def test_effective_printer_state_precedence(machine_status, device_status, stale, telemetry, request_running, expected):
    now = timezone.now()
    machine = Row(status=machine_status)
    device = Row(status=device_status, last_seen_at=now - timedelta(seconds=301 if stale else 0), offline_threshold_seconds=300)
    job = Row(telemetry_state=telemetry, telemetry_at=now, state="awaiting")
    assert effective_printer_state(machine, device, job, request_in_progress=request_running, now=now) == expected
    assert machine.status == machine_status


def test_old_or_terminal_telemetry_never_overrides_idle():
    now = timezone.now()
    machine = Row(status="idle")
    device = Row(status="active", last_seen_at=now, offline_threshold_seconds=300)
    for state, age in (("applied", 0), ("awaiting", 301)):
        job = Row(telemetry_state="running", telemetry_at=now - timedelta(seconds=age), state=state)
        assert effective_printer_state(machine, device, job, now=now) == "idle"
    device.last_seen_at = None
    assert effective_printer_state(machine, device, now=now) == "device_offline"
