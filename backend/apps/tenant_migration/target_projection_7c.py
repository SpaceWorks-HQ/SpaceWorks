"""Clear acknowledged ownership alongside 7b's shared delivery cancellation.

Label outcomes and result receipts remain history; no source print is replayed.
"""


def label_projections(field_type):
    reason = "Imported label commands cannot restart physical printing."
    return {
        ("devices.DeviceCommand", "acknowledged_at"): field_type(None, reason=reason),
    }
