"""Historical printer IDs stay source-local; live nullable FKs remap normally."""
PRINTER_SOURCE_SNAPSHOT_FIELDS = frozenset({
    ("devices.PrinterJob", "machine_id_snapshot"),
    ("devices.PrinterJob", "service_request_id_snapshot"),
    ("devices.PrinterJobConsumption", "machine_consumable_id_snapshot"),
})
