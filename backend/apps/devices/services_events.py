"""Device provenance: one immutable DeviceEvent plus one typed audit row per mutation.

A device is never an audit actor. Staff mutations pass the real User; device-originated
rows pass ``actor=None`` and carry the device identity in metadata. Metadata and event
details are allowlisted scalars -- no token, challenge, key, nonce or signature ever
reaches either table.
"""

from apps.audit import services as audit
from apps.devices.models import DeviceEvent

EventType = DeviceEvent.EventType

AUDIT_ACTIONS = {
    EventType.CREATED: "devices.created",
    EventType.UPDATED: "devices.updated",
    EventType.ENROLLMENT_CREATED: "devices.enrollment_created",
    EventType.ENROLLED: "devices.enrolled",
    EventType.ROTATION_STARTED: "devices.rotation_started",
    EventType.ROTATED: "devices.rotated",
    EventType.REVOKED: "devices.revoked",
    EventType.HEARTBEAT: "devices.heartbeat_received",
    EventType.OFFLINE: "devices.offline_detected",
    EventType.RECOVERED: "devices.recovered",
}
ALLOWED_DETAIL_KEYS = frozenset({"purpose", "changes", "status"})


def record_device_event(makerspace, device, event_type, *, actor=None, outcome="ok",
                        details=None, enrollment=None):
    details = dict(details or {})
    unknown = set(details) - ALLOWED_DETAIL_KEYS
    if unknown:
        raise ValueError(f"Device event details are not allowlisted: {sorted(unknown)}")
    event = DeviceEvent.objects.create(
        makerspace_id=device.makerspace_id,
        device=device,
        device_id_snapshot=str(device.pk),
        device_name=device.name,
        device_key_version=device.key_version,
        event_type=event_type,
        outcome=outcome,
        details=details,
    )
    audit.record(
        actor,
        AUDIT_ACTIONS[event_type],
        makerspace=makerspace,
        target=device,
        meta={
            "device_id": str(device.pk),
            "device_name": device.name,
            "device_key_version": device.key_version,
            "operation_id": str(event.operation_id),
            "outcome": outcome,
            "enrollment_id": str(enrollment.pk) if enrollment is not None else None,
            "details": details,
        },
    )
    return event
