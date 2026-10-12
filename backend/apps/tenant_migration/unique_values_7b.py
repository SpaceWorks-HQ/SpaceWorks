"""Only non-tenant-root relational uniqueness needs an explicit import disposition."""
from .unique_values_policy import REMAP, _policy

PRINTER_UNIQUE_RULES = {
    ("devices.PrinterDeviceBinding", "field:machine"): _policy(REMAP, "The remapped machine uniquely scopes its disabled printer binding."),
    ("devices.PrinterJob", "printer_live_request_once"): _policy(REMAP, "The service request reference remaps; imported command cannot execute."),
}
