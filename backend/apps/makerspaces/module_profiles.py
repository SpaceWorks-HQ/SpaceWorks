"""Install profiles for a new instance.

Opt-in modules only work if choosing them is easy. A bare Frappe-style empty
install would contradict this project's non-technical-install story, so
`setup.sh`/`setup.ps1` and `setup_instance` offer three profiles instead of
leaving the operator to discover the module system on their own.
"""

from apps.makerspaces.module_registry import MODULE_KEYS, core_module_keys, with_dependencies

MINIMAL = "minimal"
LENDING = "lending"
WORKSHOP = "workshop"
RECOMMENDED = "recommended"
EVERYTHING = "everything"

# Core plus what a makerspace lending hardware realistically needs on day one:
# the inventory lifecycle, reporting, and machines.
_RECOMMENDED_EXTRAS = frozenset({
    "guest_handover", "bulk_import", "containers", "stock_transfers", "stocktake",
    "reports", "qr_print_batches", "asset_units", "machines", "machine_service",
    "notifications", "email",
    # Member accounts and the in-app updater. A profile is an explicit set, so a key
    # that merely defaults on is NOT picked up here -- omitting them would hand a
    # freshly provisioned space no way for a member to register.
    "accounts", "updates",
})

# A tool library: the hardware lending lifecycle and nothing else. No machines, no
# events, no bookings. This is the "we only need our inventory and its flow" install.
_LENDING_EXTRAS = frozenset({
    "guest_handover", "bulk_import", "containers", "stock_transfers", "stocktake",
    "reports", "qr_print_batches", "asset_units", "email",
    # A tool library lends to people, so it needs member accounts to lend to.
    "accounts", "updates",
})

# A machine shop: the machine registry, its service queue and the maintenance that keeps
# it running. The loan spine comes along because it is core -- see the note below.
# Deliberately WITHOUT `accounts`: this is the lean install -- a shop that runs its
# machines and its inventory against its own existing login (generic OIDC, or contact
# details at the counter) and wants no member-account ecosystem at all. Adding accounts
# is one `install_module accounts` away if they later want the community layer.
_WORKSHOP_EXTRAS = frozenset({
    "machines", "machine_service", "printing", "maintenance", "reports",
    "notifications", "email", "updates",
})

PROFILES = {
    MINIMAL: "Core only -- the smallest coherent install.",
    LENDING: "A tool library: the hardware lending lifecycle, no machines.",
    WORKSHOP: "A machine shop: machines, the service queue and maintenance.",
    RECOMMENDED: "Core plus the inventory lifecycle, reports and machines.",
    EVERYTHING: "Every module (the pre-opt-in default).",
}

# NOTE ON HOW LEAN A PROFILE CAN GET. Six modules are core and no profile can drop them
# -- `public_inventory`, `request_workflow`, `staff_admin`, `evidence_uploads`,
# `qr_management`, `scanner` -- because the Hard Rules require a box QR scan AND an issue
# photo to hand hardware over, so the loan spine is the system rather than a feature of
# it. `workshop` therefore still ships the request workflow; what it does not ship is
# everything else. A deployment that wants to go further removes whole apps with
# TOMBSTONED_APPS, which is a different axis -- `suggest_tombstones` reads the installed
# modules and names the apps that are safe to drop.
DEFAULT_PROFILE = RECOMMENDED


def profile_modules(name):
    """Module keys for a profile, dependency-closed and sorted."""
    if name not in PROFILES:
        raise ValueError(f"Unknown profile {name!r}. Choose one of: {', '.join(sorted(PROFILES))}.")
    if name == EVERYTHING:
        keys = set(MODULE_KEYS)
    elif name == RECOMMENDED:
        keys = core_module_keys() | _RECOMMENDED_EXTRAS
    elif name == LENDING:
        keys = core_module_keys() | _LENDING_EXTRAS
    elif name == WORKSHOP:
        keys = core_module_keys() | _WORKSHOP_EXTRAS
    else:
        keys = set(core_module_keys())
    return sorted(with_dependencies(keys))
