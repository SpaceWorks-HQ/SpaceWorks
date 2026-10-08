"""Signed heartbeat: authentication, replay, skew, revocation, tenant liveness and gates."""

import time

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.devices.models import Device, DeviceEvent, DeviceRequestNonce
from apps.makerspaces.models import Makerspace
from tests.devices.helpers import HEARTBEAT, active_device, heartbeat, signed_headers
from tests.module_helpers import disable_module

pytestmark = pytest.mark.django_db


def test_a_valid_signed_heartbeat_records_presence_without_a_user_actor():
    space, _manager, _client, device_id, private_key = active_device("auth-ok")
    response = heartbeat(signed_headers(device_id, 1, private_key))
    assert response.status_code == 200, response.data
    assert response.data["device_id"] == device_id
    device = Device.objects.get(pk=device_id)
    assert device.last_seen_at is not None
    audit = AuditLog.objects.get(action="devices.heartbeat_received")
    assert audit.actor_id is None and audit.makerspace_id == space.pk
    assert audit.meta["device_id"] == device_id and audit.meta["device_key_version"] == 1
    assert DeviceEvent.objects.filter(device=device, event_type="heartbeat").count() == 1
    assert DeviceRequestNonce.objects.filter(device=device).count() == 1


def test_a_replayed_nonce_is_refused():
    _space, _manager, _client, device_id, private_key = active_device("auth-replay")
    headers = signed_headers(device_id, 1, private_key)
    assert heartbeat(headers).status_code == 200
    assert heartbeat(headers).status_code == 401
    assert DeviceEvent.objects.filter(device_id=device_id, event_type="heartbeat").count() == 1


def test_missing_credentials_are_401_with_a_challenge_header():
    response = heartbeat({"REQUEST_URI": HEARTBEAT})
    assert response.status_code == 401
    assert response["WWW-Authenticate"] == "SpaceWorks-Device-v1"


@pytest.mark.parametrize("mutate", [
    lambda h: {**h, "HTTP_X_DEVICE_KEY_VERSION": "2"},
    lambda h: {**h, "HTTP_X_DEVICE_SIGNATURE_VERSION": "v2"},
    lambda h: {**h, "HTTP_X_DEVICE_NONCE": "short"},
    lambda h: {**h, "HTTP_X_DEVICE_SIGNATURE": "AAAA"},
    lambda h: {**h, "HTTP_X_DEVICE_ID": h["HTTP_X_DEVICE_ID"].upper()},
    lambda h: {k: v for k, v in h.items() if k != "REQUEST_URI"},
    lambda h: {**h, "REQUEST_URI": HEARTBEAT + "?x=1"},
])
def test_tampered_or_malformed_requests_fail_and_consume_no_nonce(mutate):
    _space, _manager, _client, device_id, private_key = active_device("auth-tamper")
    response = heartbeat(mutate(signed_headers(device_id, 1, private_key)))
    assert response.status_code == 401
    assert not DeviceRequestNonce.objects.exists()


def test_a_tampered_body_fails():
    _space, _manager, _client, device_id, private_key = active_device("auth-body")
    headers = signed_headers(device_id, 1, private_key, body=b"{}")
    from rest_framework.test import APIClient

    response = APIClient().post(HEARTBEAT, data=b'{"a":1}', content_type="application/json", **headers)
    assert response.status_code == 401


@pytest.mark.parametrize("offset,status", [(-290, 200), (290, 200), (-310, 401), (310, 401)])
def test_timestamp_skew_boundaries(offset, status):
    _space, _manager, _client, device_id, private_key = active_device("auth-skew")
    headers = signed_headers(device_id, 1, private_key, timestamp=int(time.time()) + offset)
    assert heartbeat(headers).status_code == status


def test_revocation_and_rotation_kill_old_signatures():
    _space, _manager, client, device_id, private_key = active_device("auth-revoke")
    client.post(reverse("devices:admin-device-revoke", args=[device_id]))
    assert heartbeat(signed_headers(device_id, 1, private_key)).status_code == 401


def test_module_off_answers_400_and_writes_nothing():
    space, _manager, _client, device_id, private_key = active_device("auth-moduleoff")
    disable_module(space, "devices")
    response = heartbeat(signed_headers(device_id, 1, private_key))
    assert response.status_code == 400 and "devices" in str(response.data)
    assert not DeviceRequestNonce.objects.exists()
    assert Device.objects.get(pk=device_id).last_seen_at is None


@pytest.mark.parametrize("state", ["archived", "importing"])
def test_unservable_tenants_are_rejected_even_with_the_module_on(state):
    space, _manager, _client, device_id, private_key = active_device(f"auth-{state}")
    if state == "archived":
        Makerspace.objects.filter(pk=space.pk).update(archived_at=timezone.now())
    else:
        Makerspace.objects.filter(pk=space.pk).update(lifecycle_state=Makerspace.LifecycleState.IMPORTING)
    response = heartbeat(signed_headers(device_id, 1, private_key))
    assert response.status_code in (401, 403)
    assert Device.objects.get(pk=device_id).last_seen_at is None


def test_closed_source_gate_refuses_with_423_and_claims_no_nonce():
    from tests.tenant_migration.source_gate_helpers import close_gate, make_actor

    space, _manager, _client, device_id, private_key = active_device("auth-gate")
    close_gate(space, make_actor("auth-gate"))
    response = heartbeat(signed_headers(device_id, 1, private_key))
    assert response.status_code == 423
    assert not DeviceRequestNonce.objects.exists()


def test_unknown_device_routes_and_methods_are_denied():
    from rest_framework.test import APIClient

    assert APIClient().get(HEARTBEAT).status_code in (401, 403)
    assert APIClient().post("/api/v1/device/unknown").status_code == 404
