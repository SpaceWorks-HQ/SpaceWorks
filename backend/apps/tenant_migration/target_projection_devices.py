"""Target resets for imported devices (phase 7a).

An imported Device arrives PENDING with no live key, last-seen, offline or revocation
state; only a target staff enrollment plus fresh proof of possession can make it
active again. ``key_version`` is deliberately retained so the next enrollment advances
it past every signature the source deployment ever accepted. The key and fingerprint
are omitted at export (``data_export.fields.ALWAYS_OMITTED``) and reconstructed NULL.
Revocation history survives in DeviceEvent and the audit snapshots.
"""

_RESET = "Imported devices carry no live authority; the target re-enrolls them."

DEVICE_FIELD_RESETS = {
    ("devices.Device", "status"): ("pending", _RESET),
    ("devices.Device", "last_seen_at"): (None, _RESET),
    ("devices.Device", "offline_since"): (None, _RESET),
    ("devices.Device", "offline_notified_at"): (None, _RESET),
    ("devices.Device", "revoked_at"): (None, _RESET),
    ("devices.Device", "revoked_by"): (None, _RESET),
}
