"""Purge, full-restore authority reset, DB immutability and the route registry check."""

import uuid

import pytest
from django.contrib.auth import get_user_model
from django.db import connection, transaction
from django.db.utils import InternalError
from django.utils import timezone

from apps.devices.checks import discover_device_routes, registry_errors
from apps.devices.models import Device, DeviceEnrollment, DeviceEvent, DeviceRequestNonce
from apps.devices.route_registry import DEVICE_ROUTES, DeviceRoute, DEVICE_SIGNATURE
from apps.makerspaces.module_purge import purge_module
from tests.devices.helpers import active_device, heartbeat, signed_headers
from tests.module_helpers import disable_module

pytestmark = pytest.mark.django_db


def test_device_events_are_append_only_in_the_database():
    _space, _manager, _client, device_id, _private = active_device("life-trigger")
    with pytest.raises(InternalError):
        with transaction.atomic():
            DeviceEvent.objects.filter(device_id=device_id).update(outcome="forged")
    with pytest.raises(InternalError):
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM devices_deviceevent")
    assert DeviceEvent.objects.filter(device_id=device_id).exists()


def test_authorized_purge_deletes_auth_rows_then_identity_and_history():
    space, _manager, _client, device_id, private_key = active_device("life-purge")
    assert heartbeat(signed_headers(device_id, 1, private_key)).status_code == 200
    disable_module(space, "devices")
    root = get_user_model().objects.create_superuser("life-purge-root", "r@e.com", "x")
    counts = purge_module(space, "devices", root)
    assert counts["devices"] == 1 and counts["device_events"] >= 3
    for model in (Device, DeviceEnrollment, DeviceEvent, DeviceRequestNonce):
        assert not model.objects.exists(), model


def test_full_restore_quarantine_invalidates_every_device_credential():
    from apps.backup.recovery import _reset_device_authority

    _space, _manager, client, device_id, private_key = active_device("life-restore")
    captured = signed_headers(device_id, 1, private_key)  # signed before the "backup"
    pending = client.post(f"/api/v1/admin/devices/{device_id}/enrollments")
    assert pending.status_code == 201
    _reset_device_authority(timezone.now())
    device = Device.objects.get(pk=device_id)
    assert (device.status, device.public_key, device.key_fingerprint) == ("pending", None, None)
    assert device.key_version == 2
    assert not DeviceRequestNonce.objects.exists()
    assert not DeviceEnrollment.objects.filter(used_at__isnull=True, revoked_at__isnull=True).exists()
    # Still refused after quarantine is acknowledged: nothing re-arms the old key.
    assert heartbeat(captured).status_code == 401
    assert heartbeat(signed_headers(device_id, 1, private_key)).status_code == 401
    assert heartbeat(signed_headers(device_id, 2, private_key)).status_code == 401


def test_route_registry_matches_the_mounted_urlconf_exactly():
    discovered = discover_device_routes()
    assert set(discovered) == set(DEVICE_ROUTES)
    assert registry_errors(discovered) == []


def test_route_registry_check_reports_missing_stale_and_shape_drift():
    discovered = discover_device_routes()
    stale = {**DEVICE_ROUTES, ("devices:gone", "POST"): DEVICE_ROUTES[("devices:device-heartbeat", "POST")]}
    assert any("stale" in error for error in registry_errors(discovered, stale))
    partial = dict(DEVICE_ROUTES)
    partial.pop(("devices:device-heartbeat", "POST"))
    assert any("missing" in error for error in registry_errors(discovered, partial))
    swapped = {
        **DEVICE_ROUTES,
        ("devices:device-enrollment-challenge", "POST"): DeviceRoute(
            DEVICE_SIGNATURE, "x", frozenset({"printer"}), ("devices",)
        ),
    }
    assert any("authenticators" in error for error in registry_errors(discovered, swapped))


def test_json_pk_writes_uuid_audit_references_as_strings():
    from apps.tenant_migration.semantic_remap import _json_pk

    value = uuid.uuid4()
    assert _json_pk(value) == str(value)
    assert _json_pk(7) == 7 and _json_pk(None) is None


def test_device_audit_meta_remap_is_json_serializable():
    import json

    from apps.tenant_migration.semantic_remap import _remap_audit_dict

    target = uuid.uuid4()

    class PkMap:
        def lookup(self, model, value):
            assert model._meta.label == "devices.Device"
            return target

    meta = {"device_id": str(uuid.uuid4()), "operation_id": "op", "enrollment_id": "e"}
    remapped = _remap_audit_dict("devices.heartbeat_received", meta, PkMap(), "")
    assert remapped["device_id"] == str(target)
    assert (remapped["operation_id"], remapped["enrollment_id"]) == ("op", "e")
    json.dumps(remapped)
