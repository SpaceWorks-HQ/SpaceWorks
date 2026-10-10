"""Portable tenant move of device identity: fresh UUIDs, no live authority, inert snapshots."""

import pytest

from apps.audit.models import AuditLog
from apps.devices import services_identity
from apps.devices.models import Device, DeviceEnrollment, DeviceEvent, DeviceRequestNonce
from apps.makerspaces.models import Makerspace
from apps.tenant_migration.materialization import materialize_tenant
from tests.data_export.portable_helpers import make_space, make_user
from tests.encryption.conftest import enabled_encryption
from tests.tenant_migration.materialization_helpers import portable_import_case

pytestmark = pytest.mark.django_db(transaction=True)


def _devices(space, user, _request):
    space.enabled_modules = sorted(set(space.enabled_modules or []) | {"devices"})
    space.save(update_fields=["enabled_modules"])
    device, _enrollment, _token = services_identity.create_device(
        user, space.pk, kind="printer", name="Moving printer"
    )
    # Stand in for a completed enrollment: live key material the move must not carry.
    Device.objects.filter(pk=device.pk).update(
        status="active", public_key="A6EHv/POEL4dcN0Y50vAmWfk1jCbpQ1fHdyGZBJVMbg=",
        key_fingerprint="56475aa75463474c0285df5dbf2bcab73da651358839e9b77481b2eab107708c",
        key_version=3,
    )
    device.refresh_from_db()
    snapshot = DeviceEvent.objects.create(
        makerspace=space, device=device, device_id_snapshot=str(device.pk),
        device_name=device.name, device_key_version=3, event_type="heartbeat",
        machine_id_snapshot=987654,
    )
    DeviceRequestNonce.objects.create(
        device=device, key_version=3, nonce_digest="n" * 64,
        claimed_at=device.created_at, expires_at=device.created_at,
    )
    return {"device": device, "snapshot": snapshot}


def test_devices_move_as_pending_identity_with_remapped_ids_and_inert_snapshots():
    with enabled_encryption():
        user = make_user("devices-move")
        source = make_space("devices-move")
        with portable_import_case(source, user, prepare_source=_devices) as case:
            case.decide_walk_in(user)
            graph = case.source_data
            result = materialize_tenant(
                case.root, case.job, case.carried,
                target_identity={"name": "Moved devices", "slug": "moved-devices"},
                batch_size=2,
            )

    target = Makerspace.objects.get(pk=result.target_makerspace_id)
    device = Device.objects.get(makerspace=target)
    source_device = graph["device"]
    assert device.pk != source_device.pk
    assert (device.name, device.kind, device.key_version) == ("Moving printer", "printer", 3)
    assert (device.status, device.public_key, device.key_fingerprint) == ("pending", None, None)
    assert (device.last_seen_at, device.revoked_at, device.revoked_by_id) == (None, None, None)
    assert not DeviceEnrollment.objects.filter(makerspace=target).exists()
    assert not DeviceRequestNonce.objects.filter(device=device).exists()

    moved = DeviceEvent.objects.get(makerspace=target, event_type="heartbeat")
    assert moved.pk != graph["snapshot"].pk and moved.device_id == device.pk
    # Source-local history stays byte-for-byte; it is never rebound to a target row.
    assert moved.device_id_snapshot == str(source_device.pk)
    assert moved.machine_id_snapshot == 987654
    assert (moved.command_id_snapshot, moved.qr_batch_id_snapshot) == (None, None)

    audit = AuditLog.objects.get(makerspace=target, action="devices.created")
    assert audit.actor_id is None
    assert audit.meta["device_id"] == str(device.pk)
    assert (audit.target_type, audit.target_id) == ("devices.device", str(device.pk))
