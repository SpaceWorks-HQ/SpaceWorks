"""All three printer User FKs are included in the bounded creator/processor closure."""
PRINTER_USER_FIELDS = frozenset({
    ("devices.DeviceCommand", "created_by"),
    ("devices.PrinterDeviceBinding", "created_by"),
    ("devices.PrinterJob", "processed_by"),
})
