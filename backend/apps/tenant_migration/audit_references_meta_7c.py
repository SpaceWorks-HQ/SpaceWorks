from .audit_references_targets import AuditReference, AuditReferenceDisposition

R = AuditReferenceDisposition.REMAP
S = AuditReferenceDisposition.SOURCE_LOCAL_SNAPSHOT
LABEL_AUDIT_ACTIONS = (
    "devices.label_command_created", "devices.label_content_downloaded",
    "devices.label_command_succeeded", "devices.label_command_retry_scheduled",
    "devices.label_command_failed",
)
LABEL_AUDIT_EDGES = {
    **{(action, key): AuditReference(R, model) for action in LABEL_AUDIT_ACTIONS
       for key, model in [("device_id", "devices.Device"), ("command_id", "devices.DeviceCommand"),
                          ("label_command_id", "devices.LabelPrintCommand"),
                          ("qr_batch_id", "operations.QrPrintBatch")]},
    **{(action, "operation_id"): AuditReference(S, "devices.LabelPrintResult")
       for action in LABEL_AUDIT_ACTIONS},
}
LABEL_AUDIT_EDGES.update({
    (f"devices.{action}", key): AuditReference(R, model)
    for action in ("command_leased", "command_acknowledged", "command_delivery_failed")
    for key, model in (("label_command_id", "devices.LabelPrintCommand"),
                       ("qr_batch_id", "operations.QrPrintBatch"))
})
