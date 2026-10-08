"""Device audit metadata edges (phase 7a).

``device_id`` remaps to the exported Device (a fresh target UUID, written to JSONB as a
string by ``semantic_remap._json_pk``). ``enrollment_id`` names an omitted enrollment and
``operation_id`` a DeviceEvent operation, so both stay source-local snapshots.
"""

from .audit_references_targets import AuditReference, AuditReferenceDisposition

R = AuditReferenceDisposition.REMAP
S = AuditReferenceDisposition.SOURCE_LOCAL_SNAPSHOT

DEVICE_AUDIT_ACTIONS = (
    "devices.created", "devices.updated", "devices.enrollment_created", "devices.enrolled",
    "devices.rotation_started", "devices.rotated", "devices.revoked",
    "devices.heartbeat_received",
)

DEVICE_AUDIT_EDGES = {
    **{(action, "device_id"): AuditReference(R, "devices.Device") for action in DEVICE_AUDIT_ACTIONS},
    **{
        (action, "enrollment_id"): AuditReference(S, "devices.DeviceEnrollment")
        for action in DEVICE_AUDIT_ACTIONS
    },
    **{
        (action, "operation_id"): AuditReference(S, "devices.DeviceEvent")
        for action in DEVICE_AUDIT_ACTIONS
    },
}
