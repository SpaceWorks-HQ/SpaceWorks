"""Staff-side identity mutations: create, rename/re-threshold, revoke.

Status and key material change only through ``services_enrollment`` (activation,
rotation, reactivation) and ``revoke_device`` here. PATCH reaches ``update_device``,
which accepts exactly ``name`` and ``offline_threshold_seconds``.
"""

from django.db import transaction
from django.utils import timezone

from apps.devices.models import Device
from apps.devices.services_enrollment import (
    _device_makerspace_id,
    open_enrollment,
    revoke_open_enrollments,
)
from apps.devices.services_events import EventType, record_device_event
from apps.devices.services_locks import lock_tenant

UPDATABLE_FIELDS = ("name", "offline_threshold_seconds")


def create_device(actor, makerspace_id, *, kind, name, offline_threshold_seconds=300):
    with transaction.atomic():
        makerspace = lock_tenant(makerspace_id)
        device = Device.objects.create(
            makerspace=makerspace, kind=kind, name=name,
            offline_threshold_seconds=offline_threshold_seconds, created_by=actor,
        )
        record_device_event(makerspace, device, EventType.CREATED, actor=actor)
        enrollment, token = open_enrollment(actor, makerspace, device)
    return device, enrollment, token


def update_device(actor, device_id, changes):
    unknown = set(changes) - set(UPDATABLE_FIELDS)
    if unknown:
        raise ValueError(f"Not updatable: {sorted(unknown)}")
    makerspace_id = _device_makerspace_id(device_id)
    with transaction.atomic():
        makerspace = lock_tenant(makerspace_id)
        device = Device.objects.select_for_update().get(pk=device_id)
        diff = {
            field: {"before": getattr(device, field), "after": value}
            for field, value in changes.items()
            if getattr(device, field) != value
        }
        if not diff:
            return device
        for field, values in diff.items():
            setattr(device, field, values["after"])
        device.save(update_fields=sorted(diff))
        record_device_event(
            makerspace, device, EventType.UPDATED, actor=actor, details={"changes": diff},
        )
    return device


def revoke_device(actor, device_id):
    makerspace_id = _device_makerspace_id(device_id)
    with transaction.atomic():
        makerspace = lock_tenant(makerspace_id)
        device = Device.objects.select_for_update().get(pk=device_id)
        if device.status == Device.Status.REVOKED:
            return device
        now = timezone.now()
        revoke_open_enrollments(actor, device, now)
        previous = device.status
        device.status = Device.Status.REVOKED
        device.revoked_at = now
        device.revoked_by = actor
        device.save(update_fields=["status", "revoked_at", "revoked_by"])
        record_device_event(
            makerspace, device, EventType.REVOKED, actor=actor, details={"status": previous},
        )
    return device
