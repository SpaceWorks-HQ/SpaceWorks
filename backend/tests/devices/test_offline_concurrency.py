"""Database row locks serialize offline and recovery edges across workers."""

from datetime import timedelta
import threading

import pytest
from django.db import connection
from django.utils import timezone

from apps.devices.models import Device, DeviceEvent
from apps.devices.principal import DevicePrincipal
from apps.devices.services_offline import scan_offline_devices
from apps.devices.services_requests import record_heartbeat
from tests.devices.helpers import active_device

pytestmark = pytest.mark.django_db(transaction=True)


def _race(function):
    barrier = threading.Barrier(2)
    failures = []
    def fire():
        try:
            barrier.wait(timeout=30)
            function()
        except Exception as exc:
            failures.append(exc)
        finally:
            connection.close()
    threads = [threading.Thread(target=fire) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    assert not any(thread.is_alive() for thread in threads)
    assert not failures


def test_concurrent_scans_and_recoveries_emit_one_edge_each(monkeypatch):
    _space, _manager, _client, device_id, _key = active_device("offline-race")
    Device.objects.filter(pk=device_id).update(last_seen_at=timezone.now()-timedelta(hours=1))
    deliveries = []
    monkeypatch.setattr("apps.devices.services_offline.notify_device_state",
                        lambda _space, _device, event, **_kw: deliveries.append(event))
    _race(scan_offline_devices)
    principal = DevicePrincipal.from_device(Device.objects.get(pk=device_id))
    _race(lambda: record_heartbeat(principal, now=timezone.now()))
    assert DeviceEvent.objects.filter(device_id=device_id, event_type="offline_detected").count() == 1
    assert DeviceEvent.objects.filter(device_id=device_id, event_type="recovered").count() == 1
    assert deliveries == ["offline", "recovered"]
