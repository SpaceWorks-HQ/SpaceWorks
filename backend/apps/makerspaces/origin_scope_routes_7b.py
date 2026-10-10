"""Phase 7b exact origin targets; detail kwargs use pk."""
PRINTER_MAKERSPACE_ROUTES = {
    "admin-printer-binding-list": "makerspace_id", "admin-printer-job-list": "makerspace_id",
}
PRINTER_MODEL_LOOKUPS = {
    "admin-printer-binding-detail": ("devices.PrinterDeviceBinding", "makerspace_id"),
    "admin-printer-job-detail": ("devices.PrinterJob", "makerspace_id"),
    "admin-printer-job-apply": ("devices.PrinterJob", "makerspace_id"),
    "device-command-ack": ("devices.DeviceCommand", "makerspace_id"),
    "device-printer-job-telemetry": ("devices.PrinterJob", "makerspace_id"),
    "device-printer-job-result": ("devices.PrinterJob", "makerspace_id"),
}
