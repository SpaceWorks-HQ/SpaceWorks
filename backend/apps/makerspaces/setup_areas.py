"""Installer areas are bundles over the module and feature registries, not new gates."""
from .capabilities import FEATURES, feature_required_modules
from .module_registry import core_module_keys, with_dependencies

AREAS = {
    "inventory": ("public_inventory", "request_workflow", "staff_admin", "scanner",
                  "evidence_uploads", "qr_management", "guest_handover", "asset_units",
                  "containers", "bulk_import", "stock_transfers", "qr_print_batches",
                  "procurement", "stocktake", "devices"),
    "machines": ("machines", "machine_service", "printing", "maintenance"),
    "events": ("events",),
    "bookings": ("bookings",),
    "membership": ("membership", "mobile"),
    "payments": ("payments",),
    "reports": ("reports",),
    "chat": ("telegram", "slack", "mattermost", "discord", "webhook"),
}
ALWAYS_MODULES = {"backup", "notifications", "email", "member_accounts"}
ALWAYS_FEATURES = {"billing.reminders", "charges.enabled", "billing.documents",
                   "staff.invitations", "presence.geofence"}
INVENTORY_FEATURES = {"inventory.self_checkout", "inventory.kiosk"}


def modules_for(areas):
    return with_dependencies(core_module_keys() | ALWAYS_MODULES | {
        module for area in areas for module in AREAS[area]
    })


def features_for(areas, modules=None):
    """Enable all children, then remove unsatisfied prerequisites to a fixed point."""
    modules = set(modules if modules is not None else modules_for(areas))
    parents = ALWAYS_MODULES | {module for area in areas for module in AREAS[area]}
    features = ALWAYS_FEATURES | {
        key for key, definition in FEATURES.items() if definition.parent_module in parents
    }
    if "inventory" in areas:
        features |= INVENTORY_FEATURES
    else:
        # Core is installed even when lending is hidden. It must not enable loans.
        features -= {key for key in features if key.startswith(("loans.", "inventory."))}
        features -= {"charges.loans", "payments.loans"}
    while True:
        supported = {key for key in features
                     if set(feature_required_modules(key)) <= modules
                     and set(FEATURES[key].requires_features) <= features}
        if supported == features:
            return sorted(features)
        features = supported


def edition_for(areas, organization=False):
    if organization:
        return "organization"
    primary = set(areas) - {"membership", "payments", "reports", "chat"}
    return next(iter(primary)) if primary in ({"events"}, {"bookings"}) else "makerspace"


def area_status(space):
    installed = set(space.enabled_modules or [])
    features = set(space.enabled_features or [])
    result = {}
    for key, modules in AREAS.items():
        optional = set(modules) - core_module_keys()
        count = len(optional & installed)
        state = "on" if count == len(optional) else "partial" if count else "off"
        if key == "inventory":
            if "loans.enabled" not in features:
                state = "partial" if count else "off"
            elif not count:
                state = "partial"
        result[key] = state
    return result


def active_areas(space):
    """Existing domain configuration survives completing a partial module bundle."""
    modules = set(space.enabled_modules or [])
    anchors = {"machines": "machines", "events": "events", "bookings": "bookings",
               "membership": "membership", "payments": "payments", "reports": "reports"}
    return {"inventory": "loans.enabled" in (space.enabled_features or []),
            **{area: module in modules for area, module in anchors.items()},
            "chat": bool(set(AREAS["chat"]) & modules)}
