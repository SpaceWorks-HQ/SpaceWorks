"""Real concurrency: two valid requests carrying one nonce -- exactly one commits."""

import threading

import pytest
from django.db import connection

from apps.devices.models import DeviceEvent, DeviceRequestNonce
from tests.devices.helpers import active_device, heartbeat, signed_headers

pytestmark = pytest.mark.django_db(transaction=True)


def test_one_nonce_raced_by_two_requests_commits_exactly_once():
    _space, _manager, _client, device_id, private_key = active_device("race-nonce")
    headers = signed_headers(device_id, 1, private_key)
    barrier = threading.Barrier(2)
    statuses = []

    def fire():
        try:
            barrier.wait()
            statuses.append(heartbeat(headers).status_code)
        finally:
            connection.close()

    threads = [threading.Thread(target=fire) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)

    assert sorted(statuses) == [200, 401]
    assert DeviceRequestNonce.objects.filter(device_id=device_id).count() == 1
    assert DeviceEvent.objects.filter(device_id=device_id, event_type="heartbeat").count() == 1
