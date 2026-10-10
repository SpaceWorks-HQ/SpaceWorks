"""Printer report identity and state contain no delivery credential."""
PRINTER_NON_CREDENTIAL = {
    ("devices.PrinterJob", "state"): "Durable report/application workflow state.",
    ("devices.PrinterJob", "telemetry_state"): "Advisory printer telemetry enum.",
    ("devices.PrinterJob", "report_sha256"): "Canonical measurement integrity hash, never authentication.",
}
