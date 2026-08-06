"""Install profiles for a new instance.

Opt-in modules only work if choosing them is easy. A bare Frappe-style empty
install would contradict this project's non-technical-install story, so
`setup.sh`/`setup.ps1` and `setup_instance` offer three profiles instead of
leaving the operator to discover the module system on their own.
"""

from apps.makerspaces.module_registry import MODULE_KEYS, core_module_keys, with_dependencies

MINIMAL = "minimal"
RECOMMENDED = "recommended"
EVERYTHING = "everything"

# Core plus what a makerspace lending hardware realistically needs on day one:
# the inventory lifecycle, reporting, and machines.
_RECOMMENDED_EXTRAS = frozenset({
    "guest_handover", "bulk_import", "containers", "stock_transfers", "stocktake",
    "reports", "qr_print_batches", "asset_units", "machines", "machine_service",
    "notifications",
})

PROFILES = {
    MINIMAL: "Core only -- the smallest coherent install.",
    RECOMMENDED: "Core plus the inventory lifecycle, reports and machines.",
    EVERYTHING: "Every module (the pre-opt-in default).",
}
DEFAULT_PROFILE = RECOMMENDED


def profile_modules(name):
    """Module keys for a profile, dependency-closed and sorted."""
    if name not in PROFILES:
        raise ValueError(f"Unknown profile {name!r}. Choose one of: {', '.join(sorted(PROFILES))}.")
    if name == EVERYTHING:
        keys = set(MODULE_KEYS)
    elif name == RECOMMENDED:
        keys = core_module_keys() | _RECOMMENDED_EXTRAS
    else:
        keys = set(core_module_keys())
    return sorted(with_dependencies(keys))
