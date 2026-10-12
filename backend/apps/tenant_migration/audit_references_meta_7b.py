"""Typed printer audit IDs remap through the actual target rows; event IDs stay source-local."""
from .audit_references_targets import AuditReference, AuditReferenceDisposition

PRINTER_AUDIT_ACTIONS = (
    "printer_bound", "printer_unbound", "printer_job_created", "command_leased", "command_acknowledged",
    "command_delivery_failed", "printer_telemetry_received", "printer_result_claimed", "printer_result_applied",
    "printer_result_needs_review", "printer_job_cancelled",
)
PRINTER_AUDIT_EDGES = {
    (f"devices.{action}", field): AuditReference(AuditReferenceDisposition.REMAP, label)
    for action in PRINTER_AUDIT_ACTIONS
    for field, label in (("device_id", "devices.Device"), ("command_id", "devices.DeviceCommand"),
                         ("printer_job_id", "devices.PrinterJob"), ("machine_id", "machines.Machine"),
                         ("service_request_id", "machines.MachineServiceRequest"))
}
PRINTER_AUDIT_EDGES.update({
    (f"devices.{action}", "operation_id"): AuditReference(AuditReferenceDisposition.SOURCE_LOCAL_SNAPSHOT, "devices.DeviceEvent")
    for action in PRINTER_AUDIT_ACTIONS
})
