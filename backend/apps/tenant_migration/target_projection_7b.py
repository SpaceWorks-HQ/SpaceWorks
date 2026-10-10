"""Imported remote delivery is permanently inert; applied history remains readable."""


def printer_projections(field_type):
    reason = "Imported printer authority must be re-created explicitly on the target."
    result = {
        ("devices.DeviceCommand", "status"): field_type("cancelled", reason=reason),
        ("devices.DeviceCommand", "lease_token_digest"): field_type(None, reason=reason),
        ("devices.DeviceCommand", "lease_expires_at"): field_type(None, reason=reason),
        ("devices.PrinterDeviceBinding", "enabled"): field_type(False, reason=reason),
        ("devices.PrinterDeviceBinding", "auto_apply_terminal"): field_type(False, reason=reason),
        ("devices.PrinterJob", "state"): field_type("needs_review", condition=("state", frozenset({"awaiting", "reported", "needs_review"})), reason=reason),
    }
    return result
