"""Lane D authority rules for device identity (phase 7a).

Device identity travels, its live authority does not: status, key material and the
last-seen/offline/revocation markers reset (to the field defaults -- pending and NULL)
so a moved device must enroll again on the target. ``key_version`` is preserved so the
next enrollment advances past every source signature.
"""

from .tenant_dump_types import AuthorityDisposition as D
from .tenant_dump_types import authority

_RESET = "A device key is proven per deployment; the target device re-enrolls."

DEVICE_AUTHORITY_ENTRIES = tuple(
    (("devices.Device", name), authority(D.RESET, _RESET))
    for name in (
        "status public_key key_fingerprint last_seen_at offline_since "
        "offline_notified_at revoked_at revoked_by"
    ).split()
) + (
    (("devices.Device", "key_version"), authority(
        D.PRESERVE, "Monotonic: the target's first enrollment must exceed it."
    )),
)

from .tenant_dump_authority_7b import PRINTER_AUTHORITY_ENTRIES

DEVICE_AUTHORITY_ENTRIES += PRINTER_AUTHORITY_ENTRIES
