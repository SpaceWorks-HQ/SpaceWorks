"""Publication preferences are portable, still bounded by target capabilities.

No target reset is needed: these are preserved settings, like the existing
public_inventory_enabled. No new models or User references are introduced.
"""

from .tenant_dump_types import AuthorityDisposition as D, authority

MODULE_FIELD_NAMES = frozenset({"public_site_enabled", "public_landing_page"})
MODULE_AUTHORITY_ENTRIES = tuple(
    (("makerspaces.Makerspace", field), authority(
        D.PRESERVE, "Tenant publication choice, bounded by target modules and features.",
    ))
    for field in sorted(MODULE_FIELD_NAMES)
)
