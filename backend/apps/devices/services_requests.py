"""Signed-request admission (atomic nonce claim) and the heartbeat mutation.

PostgreSQL uniqueness is the replay authority, not a cache: the nonce is INSERTed only
after the signature verifies (an invalid signature consumes nothing) and under the
Device row lock, so two concurrent valid requests carrying one nonce cannot both win.
The heartbeat re-takes the makerspace-first locks because revocation, rotation or a
module uninstall can commit between authentication and the view.
"""

from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from rest_framework.exceptions import AuthenticationFailed, PermissionDenied

from apps.devices import protocol
from apps.devices.models import Device, DeviceRequestNonce
from apps.devices.principal import DevicePrincipal
from apps.devices.services_events import EventType, record_device_event
from apps.devices.services_locks import lock_tenant
from apps.ed25519 import Ed25519Error, verify_bytes


def claim_signed_request(*, device_id, makerspace_id, key_version, nonce, message, signature, now):
    with transaction.atomic():
        lock_tenant(makerspace_id)
        device = Device.objects.select_for_update().get(pk=device_id)
        _assert_current(device, key_version)
        try:
            raw_key = protocol.b64_decode(device.public_key, label="public key", length=32)
            verify_bytes(message, signature, raw_key)
        except (protocol.ProtocolError, Ed25519Error) as exc:
            raise AuthenticationFailed("Invalid device signature.") from exc
        try:
            with transaction.atomic():
                DeviceRequestNonce.objects.create(
                    device=device, key_version=key_version,
                    nonce_digest=protocol.sha256_hex(nonce.encode("ascii")),
                    claimed_at=now,
                    expires_at=now + timedelta(seconds=settings.DEVICE_NONCE_TTL_SECONDS),
                )
        except IntegrityError as exc:
            raise AuthenticationFailed("Replayed device request.") from exc
        DeviceRequestNonce.objects.filter(device=device, expires_at__lte=now).delete()
    return DevicePrincipal.from_device(device)


def record_heartbeat(principal, *, now):
    with transaction.atomic():
        makerspace = lock_tenant(principal.makerspace_id)
        device = Device.objects.select_for_update().get(pk=principal.device_id)
        if device.status != Device.Status.ACTIVE or device.key_version != principal.key_version:
            raise PermissionDenied("Device authorization is no longer active.")
        device.last_seen_at = now
        device.offline_since = None
        device.save(update_fields=["last_seen_at", "offline_since"])
        record_device_event(makerspace, device, EventType.HEARTBEAT)
    return device


def _assert_current(device, key_version):
    if (
        device.status != Device.Status.ACTIVE
        or device.key_version != key_version
        or not device.public_key
    ):
        raise AuthenticationFailed("Device authorization is not active.")
