"""Offline threshold edges, signed recovery and bounded artifact retention."""

from datetime import timedelta, timezone as datetime_timezone
import uuid

import pytest
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.devices.models import Device, DeviceEnrollment, DeviceEvent, DeviceRequestNonce
from apps.devices.services_offline import scan_offline_devices
from tests.devices.helpers import active_device, create_device, heartbeat, signed_headers

pytestmark = pytest.mark.django_db


def test_threshold_boundary_and_repeated_scan_are_one_edge(monkeypatch):
    space, _manager, _client, device_id, private = active_device("offline-edge")
    seen = timezone.now().astimezone(datetime_timezone(timedelta(hours=5, minutes=30)))
    Device.objects.filter(pk=device_id).update(last_seen_at=seen, offline_threshold_seconds=60)
    notifications = []
    monkeypatch.setattr("apps.devices.services_offline.notify_device_state",
                        lambda _space, _device, event, **_kw: notifications.append(event))
    assert scan_offline_devices(now=seen + timedelta(seconds=59))["offline"] == 0
    assert scan_offline_devices(now=seen + timedelta(seconds=60))["offline"] == 1
    assert scan_offline_devices(now=seen + timedelta(seconds=61))["offline"] == 0
    row = Device.objects.get(pk=device_id)
    assert row.offline_since == seen + timedelta(seconds=60)
    assert row.offline_notified_at == seen + timedelta(seconds=60)
    assert DeviceEvent.objects.filter(device=row, event_type="offline_detected").count() == 1
    assert AuditLog.objects.filter(makerspace=space, action="devices.offline_detected", actor=None).count() == 1
    assert heartbeat(signed_headers(device_id, 1, private)).status_code == 200
    assert heartbeat(signed_headers(device_id, 1, private)).status_code == 200
    row.refresh_from_db()
    assert row.offline_since is None and row.offline_notified_at is None
    assert DeviceEvent.objects.filter(device=row, event_type="recovered").count() == 1
    assert notifications == ["offline", "recovered"]


def test_never_seen_active_uses_immutable_activation_event_and_pending_is_ignored():
    _space, _manager, client, device_id, _private = active_device("offline-never-seen")
    row = Device.objects.get(pk=device_id)
    created = create_device(client, row.makerspace, name="Pending forever")
    activation = row.events.get(event_type="enrolled").created_at
    DeviceEnrollment.objects.filter(device=row).delete()
    assert row.last_seen_at is None
    assert scan_offline_devices(now=activation + timedelta(seconds=299))["offline"] == 0
    assert scan_offline_devices(now=activation + timedelta(seconds=300))["offline"] == 1
    assert Device.objects.get(pk=created["device"]["id"]).offline_since is None


def test_revoked_device_is_not_marked_offline():
    _space, _manager, client, device_id, _private = active_device("offline-revoked")
    from django.urls import reverse
    assert client.post(reverse("devices:admin-device-revoke", args=[device_id])).status_code == 200
    assert scan_offline_devices(now=timezone.now() + timedelta(days=1))["offline"] == 0
    assert not DeviceEvent.objects.filter(device_id=device_id, event_type="offline_detected").exists()


def test_cleanup_is_bounded_terminal_expired_only_and_tenant_scoped():
    space, _manager, client, device_id, _private = active_device("offline-cleanup")
    now = timezone.now()
    row = Device.objects.get(pk=device_id)
    Device.objects.filter(pk=device_id).update(last_seen_at=now)
    for index in range(5):
        DeviceRequestNonce.objects.create(device=row, key_version=1, nonce_digest=f"{index:064x}",
                                         claimed_at=now-timedelta(hours=1), expires_at=now-timedelta(seconds=2))
        DeviceEnrollment.objects.create(makerspace=space, device=row, purpose="enroll",
                                        token_digest=uuid.uuid4().hex, expires_at=now,
                                        revoked_at=now-timedelta(hours=1))
    pending = create_device(client, space, name="Pending")
    DeviceEnrollment.objects.filter(pk=pending["enrollment"]["enrollment_id"]).update(expires_at=now)
    future_nonce = DeviceRequestNonce.objects.create(device=row, key_version=1, nonce_digest="f"*64,
                                                      claimed_at=now, expires_at=now+timedelta(minutes=1))
    before = DeviceEvent.objects.count()
    result = scan_offline_devices(now=now, batch_size=2)
    assert (result["nonces"], result["enrollments"]) == (2, 2)
    assert DeviceRequestNonce.objects.filter(device=row).count() == 4
    assert DeviceRequestNonce.objects.filter(pk=future_nonce.pk).exists()
    assert DeviceEnrollment.objects.filter(pk=pending["enrollment"]["enrollment_id"]).exists()
    assert DeviceEvent.objects.count() == before
    assert AuditLog.objects.filter(makerspace=space, action="devices.auth_artifacts_purged").count() == 1


def test_failed_or_replayed_signed_request_cannot_recover():
    _space, _manager, _client, device_id, private = active_device("offline-invalid")
    headers = signed_headers(device_id, 1, private)
    assert heartbeat(headers).status_code == 200
    Device.objects.filter(pk=device_id).update(last_seen_at=timezone.now()-timedelta(hours=1))
    scan_offline_devices()
    assert heartbeat(headers).status_code == 401
    invalid = signed_headers(device_id, 1, private)
    invalid["HTTP_X_DEVICE_SIGNATURE"] = "A" * 86 + "=="
    assert heartbeat(invalid).status_code == 401
    assert Device.objects.get(pk=device_id).offline_since is not None
    assert not DeviceEvent.objects.filter(device_id=device_id, event_type="recovered").exists()


def test_cleanup_keeps_nonce_through_inclusive_timestamp_boundary():
    space, _manager, _client, device_id, _private = active_device("offline-nonce-boundary")
    row = Device.objects.get(pk=device_id)
    expiry = timezone.now()
    nonce = DeviceRequestNonce.objects.create(device=row, key_version=1, nonce_digest="a"*64,
                                              claimed_at=expiry-timedelta(hours=1), expires_at=expiry)
    scan_offline_devices(now=expiry+timedelta(milliseconds=500))
    assert DeviceRequestNonce.objects.filter(pk=nonce.pk).exists()
    scan_offline_devices(now=expiry+timedelta(seconds=2))
    assert not DeviceRequestNonce.objects.filter(pk=nonce.pk).exists()


def test_reactivation_starts_fresh_observation_window():
    from django.urls import reverse
    from tests.devices.helpers import enroll
    _space, _manager, client, device_id, _private = active_device("offline-reactivate")
    Device.objects.filter(pk=device_id).update(last_seen_at=timezone.now()-timedelta(days=1))
    scan_offline_devices()
    assert client.post(reverse("devices:admin-device-revoke", args=[device_id])).status_code == 200
    grant = client.post(reverse("devices:admin-device-enrollment-create", args=[device_id]))
    response, _private, _public = enroll(grant.data)
    assert response.status_code == 200
    row = Device.objects.get(pk=device_id)
    assert row.last_seen_at is None and row.offline_since is None and row.offline_notified_at is None
    assert scan_offline_devices()["offline"] == 0
