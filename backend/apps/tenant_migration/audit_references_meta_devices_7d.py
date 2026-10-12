"""Typed device state-edge references; no authentication material travels here."""

from .audit_references_targets import AuditReference, AuditReferenceDisposition

ACTIONS = ("devices.offline_detected", "devices.recovered")
DEVICE_7D_AUDIT_EDGES = {
    **{(action, "device_id"): AuditReference(AuditReferenceDisposition.REMAP, "devices.Device")
       for action in ACTIONS},
    **{(action, "operation_id"): AuditReference(AuditReferenceDisposition.SOURCE_LOCAL_SNAPSHOT,
                                               "devices.DeviceEvent") for action in ACTIONS},
    **{(action, "enrollment_id"): AuditReference(AuditReferenceDisposition.SOURCE_LOCAL_SNAPSHOT,
                                                "devices.DeviceEnrollment") for action in ACTIONS},
}
