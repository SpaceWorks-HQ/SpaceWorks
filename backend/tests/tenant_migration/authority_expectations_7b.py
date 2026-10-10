"""Independent literal authority pin for phase 7b (never derived from production rules)."""
from apps.tenant_migration.tenant_dump_types import AuthorityDisposition as D

PRINTER_EXPECTED = {
    ("devices.DeviceCommand", "status"): (D.RESET,),
    ("devices.DeviceCommand", "lease_token_digest"): (D.RESET,),
    ("devices.DeviceCommand", "lease_expires_at"): (D.RESET,),
    ("devices.DeviceCommand", "device_key_version"): (D.PRESERVE,),
    ("devices.PrinterDeviceBinding", "enabled"): (D.RESET,),
    ("devices.PrinterDeviceBinding", "auto_apply_terminal"): (D.RESET,),
    ("devices.PrinterJob", "state"): (D.PRESERVE, D.RESET),
    ("devices.PrinterJob", "terminal_operation_id"): (D.PRESERVE,),
    ("devices.PrinterJob", "failure_reason"): (D.PRESERVE,),
}
