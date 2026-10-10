"""Staff device lifecycle and proof-of-possession enrollment over HTTP."""

from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.audit.models import AuditLog
from apps.devices.models import Device, DeviceEnrollment, DeviceEvent
from apps.devices.protocol import sha256_hex
from apps.ed25519 import encode_key, generate_keypair
from tests.devices.helpers import active_device, create_device, device_space, enroll, staff_client

pytestmark = pytest.mark.django_db


def test_create_returns_the_token_once_and_stores_only_its_digest():
    space = device_space("dev-create")
    manager, client = staff_client(space, "dev-create-mgr")
    created = create_device(client, space, name="  Label maker  ", kind="label_printer")
    device = Device.objects.get(pk=created["device"]["id"])
    assert (device.status, device.name, device.key_version) == ("pending", "Label maker", 0)
    enrollment = DeviceEnrollment.objects.get(device=device)
    token = created["enrollment"]["token"]
    assert enrollment.token_digest == sha256_hex(token.encode()) and token not in enrollment.token_digest
    assert created["enrollment"]["purpose"] == "enroll"
    actions = set(AuditLog.objects.filter(makerspace=space).values_list("action", flat=True))
    assert {"devices.created", "devices.enrollment_created"} <= actions
    audit = AuditLog.objects.get(action="devices.created")
    assert audit.actor_id == manager.pk and audit.meta["device_id"] == str(device.pk)
    assert token not in str(list(AuditLog.objects.values_list("meta", flat=True)))


def test_enrollment_activates_the_device_and_is_single_use():
    space = device_space("dev-enroll")
    _manager, client = staff_client(space, "dev-enroll-mgr")
    created = create_device(client, space)
    response, private_key, public_key = enroll(created["enrollment"])
    assert response.status_code == 200, response.data
    assert response.data["device_id"] == created["device"]["id"]
    device = Device.objects.get(pk=created["device"]["id"])
    assert (device.status, device.key_version, device.public_key) == ("active", 1, public_key)
    assert DeviceEvent.objects.filter(device=device, event_type="enrolled").count() == 1
    again = APIClient().post(
        reverse("devices:device-enrollment-challenge", args=[created["enrollment"]["enrollment_id"]]),
        {"token": created["enrollment"]["token"], "public_key": public_key}, format="json",
    )
    assert again.status_code == 410


def test_wrong_token_and_unknown_enrollment_look_identical():
    space = device_space("dev-badtoken")
    _manager, client = staff_client(space, "dev-badtoken-mgr")
    created = create_device(client, space)
    _priv, raw = generate_keypair()
    body = {"token": "nope", "public_key": encode_key(raw)}
    wrong = APIClient().post(
        reverse("devices:device-enrollment-challenge", args=[created["enrollment"]["enrollment_id"]]),
        body, format="json",
    )
    unknown = APIClient().post(
        reverse("devices:device-enrollment-challenge", args=["00000000-0000-4000-8000-000000000009"]),
        body, format="json",
    )
    assert wrong.status_code == unknown.status_code == 403


def test_expired_enrollment_is_gone():
    space = device_space("dev-expired")
    _manager, client = staff_client(space, "dev-expired-mgr")
    created = create_device(client, space)
    DeviceEnrollment.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
    _priv, raw = generate_keypair()
    response = APIClient().post(
        reverse("devices:device-enrollment-challenge", args=[created["enrollment"]["enrollment_id"]]),
        {"token": created["enrollment"]["token"], "public_key": encode_key(raw)}, format="json",
    )
    assert response.status_code == 410


def test_a_signature_from_a_different_key_is_rejected():
    space = device_space("dev-wrongkey")
    _manager, client = staff_client(space, "dev-wrongkey-mgr")
    created = create_device(client, space)
    other_private, _ = generate_keypair()
    _p, raw = generate_keypair()
    response, _, _ = enroll(created["enrollment"], private_key=other_private, public_key=encode_key(raw))
    assert response.status_code == 403
    assert Device.objects.get(pk=created["device"]["id"]).status == "pending"


def test_a_key_bound_to_another_device_conflicts():
    space, _manager, client, _device_id, private_key = active_device("dev-dupkey")
    taken = Device.objects.get(status="active").public_key
    second = create_device(client, space, name="Second")
    response = APIClient().post(
        reverse("devices:device-enrollment-challenge", args=[second["enrollment"]["enrollment_id"]]),
        {"token": second["enrollment"]["token"], "public_key": taken}, format="json",
    )
    assert response.status_code == 409


def test_rotation_keeps_the_old_key_until_the_swap_then_advances_the_version():
    space, _manager, client, device_id, old_private = active_device("dev-rotate")
    grant = client.post(reverse("devices:admin-device-enrollment-create", args=[device_id]))
    assert grant.status_code == 201 and grant.data["purpose"] == "rotate"
    device = Device.objects.get(pk=device_id)
    assert (device.status, device.key_version) == ("active", 1)  # old key still authoritative
    response, _new_private, new_public = enroll(grant.data)
    assert response.status_code == 200, response.data
    device.refresh_from_db()
    assert (device.key_version, device.public_key) == (2, new_public)
    assert AuditLog.objects.filter(action="devices.rotated", makerspace=space).count() == 1


def test_revocation_blocks_and_reactivation_needs_fresh_proof():
    _space, _manager, client, device_id, _private = active_device("dev-revoke")
    revoked = client.post(reverse("devices:admin-device-revoke", args=[device_id]))
    assert revoked.status_code == 200 and revoked.data["status"] == "revoked"
    grant = client.post(reverse("devices:admin-device-enrollment-create", args=[device_id]))
    assert grant.data["purpose"] == "reactivate"
    response, _p, _k = enroll(grant.data)
    assert response.status_code == 200
    device = Device.objects.get(pk=device_id)
    assert (device.status, device.key_version, device.revoked_at) == ("active", 2, None)


def test_new_enrollment_revokes_the_unconsumed_predecessor():
    space = device_space("dev-supersede")
    _manager, client = staff_client(space, "dev-supersede-mgr")
    created = create_device(client, space)
    device_id = created["device"]["id"]
    client.post(reverse("devices:admin-device-enrollment-create", args=[device_id]))
    first = DeviceEnrollment.objects.get(pk=created["enrollment"]["enrollment_id"])
    assert first.revoked_at is not None
    assert DeviceEnrollment.objects.filter(device_id=device_id, revoked_at__isnull=True).count() == 1


def test_patch_changes_only_name_and_threshold():
    _space, _manager, client, device_id, _private = active_device("dev-patch")
    url = reverse("devices:admin-device-detail", args=[device_id])
    ok = client.patch(url, {"name": "Renamed", "offline_threshold_seconds": 60}, format="json")
    assert ok.status_code == 200 and (ok.data["name"], ok.data["offline_threshold_seconds"]) == ("Renamed", 60)
    audit = AuditLog.objects.get(action="devices.updated")
    assert audit.meta["details"]["changes"]["name"] == {"before": "Prusa MK4", "after": "Renamed"}
    for body in ({"kind": "generic"}, {"status": "revoked"}, {"key_version": 9},
                 {"public_key": "x"}, {"makerspace": 1}, {"name": "   "},
                 {"offline_threshold_seconds": 0}, {}):
        assert client.patch(url, body, format="json").status_code == 400, body
    device = Device.objects.get(pk=device_id)
    assert (device.kind, device.status, device.key_version) == ("printer", "active", 1)


def test_device_events_are_append_only_in_the_orm():
    _space, _manager, _client, device_id, _private = active_device("dev-immutable")
    event = DeviceEvent.objects.filter(device_id=device_id).first()
    with pytest.raises(RuntimeError):
        event.save()
    with pytest.raises(RuntimeError):
        event.delete()
