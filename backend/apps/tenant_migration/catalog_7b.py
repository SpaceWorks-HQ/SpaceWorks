"""Literal phase 7b projected model/field universe (independent of export registry)."""

PRINTER_PROJECTED_LABELS = frozenset(["devices.DeviceCommand","devices.PrinterDeviceBinding","devices.PrinterJob","devices.PrinterJobConsumption"])

PRINTER_FIELD_NAMES = {
    "devices.DeviceCommand": frozenset("id makerspace device device_key_version kind status attempts next_attempt_at lease_token_digest lease_expires_at acknowledged_at last_error_code created_by created_at updated_at".split()),
    "devices.PrinterDeviceBinding": frozenset("id makerspace device machine enabled auto_apply_terminal created_by created_at updated_at".split()),
    "devices.PrinterJob": frozenset("id command makerspace device machine service_request machine_id_snapshot machine_name service_request_id_snapshot service_request_name external_job_id state telemetry_state progress_percent telemetry_at terminal_operation_id report_sha256 outcome actual_minutes failure_reason percent_complete actual_grams actual_quantity reported_at applied_at processed_by created_at".split()),
    "devices.PrinterJobConsumption": frozenset("id job machine_consumable machine_consumable_id_snapshot quantity".split()),
}
