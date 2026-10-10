"""Every ``accounts.User`` edge on the device models (phase 7a).

The exported Device's creator joins the user closure like any other staff creator;
its revoker is declared but its value is cleared with the target's revocation state
(history survives in DeviceEvent/audit snapshots). The enrollment edges are declared
only so user-edge completeness stays total -- the model itself is omitted, so they
never pull anyone into the closure.
"""

DEVICE_USER_FIELDS = frozenset(
    {
        ("devices.Device", "created_by"),
        ("devices.Device", "revoked_by"),
        ("devices.DeviceEnrollment", "created_by"),
        ("devices.DeviceEnrollment", "revoked_by"),
    }
)

DEVICE_EXCLUDED_USER_EDGE_REASONS = {
    ("devices.DeviceEnrollment", "created_by"): (
        "Omitted live enrollment authority must not contribute to the user closure."
    ),
    ("devices.DeviceEnrollment", "revoked_by"): (
        "Omitted live enrollment authority must not contribute to the user closure."
    ),
}
