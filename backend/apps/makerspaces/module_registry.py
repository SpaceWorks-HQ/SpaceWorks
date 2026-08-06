"""Canonical registry of makerspace modules.

Single source of truth for module keys, their defaults, frontend exposure and
inter-module dependencies. The parallel hand-kept lists that used to drift apart
-- ``models.DEFAULT_ENABLED_MODULES``, ``platform.MODULE_WORKFLOWS``,
``capabilities.FEATURE_MODULES`` and the hardcoded ``printing -> machine_service``
rule -- all derive from here now.

This module must NOT import ``apps.makerspaces.models``. ``models`` imports the
derived helpers from here, so the reverse edge would be a circular import.
"""

from dataclasses import dataclass, field

# How a key is actually enforced at runtime. The drift guard
# (tests/makerspaces/test_module_registry.py) parses the codebase and asserts the
# declared value matches reality, so a new module cannot ship unenforced by accident.
GUARD = "guard"  # module_enabled(...) / require_module(...) call sites
FEATURE_PARENT = "feature_parent"  # only enforced as the parent module of a feature
NONE = "none"  # deliberately unenforced (must be justified in `description`)


@dataclass(frozen=True)
class ModuleDefinition:
    key: str
    label: str
    description: str
    app_label: str
    enforcement: str
    # Modules that must also be enabled for this one to be valid. Replaces the
    # hardcoded printing -> machine_service branch in `validate_capabilities`.
    requires_modules: tuple[str, ...] = ()
    default_enabled: bool = True
    # Core modules are not toggleable: the system is incoherent without them. The
    # Hard Rules require a box QR scan AND an issue photo to hand hardware over, so
    # evidence/QR/scanner are core alongside the catalogue, request flow and staff API.
    is_core: bool = False
    # False => an internal master switch that must never appear in the bootstrap
    # `modules`/`workflows` arrays, or the byte-for-byte payload invariant breaks.
    frontend_exposed: bool = True
    frontend_workflows: tuple[str, ...] = field(default_factory=tuple)


MODULES = (
    ModuleDefinition(
        "public_inventory", "Public inventory", "Public browse catalogue and item detail.",
        "inventory", GUARD, is_core=True, frontend_workflows=("catalog",),
    ),
    ModuleDefinition(
        "request_workflow", "Request workflow", "Member hardware requests and their status.",
        "hardware_requests", GUARD, is_core=True,
        frontend_workflows=("request_submit", "request_status"),
    ),
    ModuleDefinition(
        "staff_admin", "Staff admin", "Staff console inventory and request administration.",
        "admin_api", GUARD, is_core=True,
        frontend_workflows=("staff_inventory", "staff_requests"),
    ),
    ModuleDefinition(
        "guest_handover", "Guest handover", "Guest admin issue and return of accepted requests.",
        "hardware_requests", GUARD, frontend_workflows=("guest_issue", "guest_return"),
    ),
    ModuleDefinition(
        "scanner", "Scanner", "QR scanning and container lookup.",
        "boxes", GUARD, is_core=True, frontend_workflows=("qr_scan", "container_lookup"),
    ),
    ModuleDefinition(
        "printing", "Printing", "3D print request queue (a machine type under `machines`).",
        "machines", GUARD, requires_modules=("machine_service",),
        frontend_workflows=("printing_requests",),
    ),
    ModuleDefinition(
        "telegram", "Telegram", "Per-makerspace Telegram group alerts and callbacks.",
        "integrations", GUARD, frontend_workflows=("telegram_alerts",),
    ),
    ModuleDefinition(
        "evidence_uploads", "Evidence uploads", "Immutable issue and return evidence photos.",
        "evidence", GUARD, is_core=True, frontend_workflows=("evidence_uploads",),
    ),
    ModuleDefinition(
        "qr_management", "QR management", "QR generation, revocation and printing.",
        "boxes", GUARD, is_core=True,
        frontend_workflows=("qr_generate", "qr_revoke", "qr_print"),
    ),
    ModuleDefinition(
        "bulk_import", "Bulk import", "Spreadsheet import of inventory rows.",
        "admin_api", GUARD, frontend_workflows=("bulk_import",),
    ),
    ModuleDefinition(
        "containers", "Containers", "Physical container hierarchy and moves.",
        "operations", GUARD, frontend_workflows=("container_lookup", "container_move"),
    ),
    ModuleDefinition(
        "stock_transfers", "Stock transfers", "Intra- and cross-makerspace stock movement.",
        "operations", GUARD, frontend_workflows=("stock_transfer",),
    ),
    ModuleDefinition(
        "stocktake", "Stocktake", "Scan-first stocktake sessions and variance.",
        "operations", GUARD, frontend_workflows=("stocktake",),
    ),
    ModuleDefinition(
        "reports", "Reports", "Analytics, report registry and CSV/XLSX exports.",
        "operations", GUARD, frontend_workflows=("analytics", "report_export"),
    ),
    ModuleDefinition(
        "qr_print_batches", "QR print batches", "Batched QR label ZIP generation.",
        "operations", GUARD, frontend_workflows=("qr_print_batch",),
    ),
    ModuleDefinition(
        "asset_units", "Asset units", "Individually QR-tracked asset units.",
        "inventory", GUARD, frontend_workflows=("asset_qr_generation",),
    ),
    ModuleDefinition(
        "procurement", "Procurement", "To-buy list and procurement tracking.",
        "procurement", GUARD, frontend_workflows=("procurement",),
    ),
    ModuleDefinition(
        "machines", "Machines", "Machine registry, operators, usage and documents.",
        "machines", GUARD,
    ),
    ModuleDefinition(
        "machine_service", "Machine service", "Machine service requests and consoles.",
        "machines", GUARD, frontend_workflows=("machine_service_requests",),
    ),
    ModuleDefinition(
        "events", "Events", "Event scheduling and registrations.", "events", GUARD,
    ),
    ModuleDefinition(
        "bookings", "Bookings", "Resource booking and public self-booking.", "bookings", GUARD,
    ),
    ModuleDefinition(
        "maintenance", "Maintenance", "Maintenance schedules and work orders.",
        "maintenance", GUARD, frontend_workflows=("maintenance",),
    ),
    ModuleDefinition(
        "membership", "Membership", "Community membership, waivers and referrals.",
        "makerspaces", FEATURE_PARENT,
    ),
    # Enforced by apps/notifications, but historically absent from the defaults list --
    # which is why the /control/ matrix (choices = defaults + keys already on the row)
    # can never offer it on a new makerspace. Registering it here makes it known;
    # sourcing the admin choices from this registry is the actual fix (phase 3).
    ModuleDefinition(
        "notifications", "Notifications", "In-app notification inbox and emitters.",
        "notifications", GUARD, default_enabled=False,
    ),
)

BY_KEY = {definition.key: definition for definition in MODULES}
MODULE_KEYS = frozenset(BY_KEY)


def default_enabled_module_keys():
    """Enabled-by-default module keys for a new makerspace (a fresh list every call).

    Returned fresh because this backs a JSONField default: handing out the registry's
    own collection would let one makerspace's row mutate every future default.
    """
    return [definition.key for definition in MODULES if definition.default_enabled]


def core_module_keys():
    """Keys that are always on and must not be disabled."""
    return frozenset(definition.key for definition in MODULES if definition.is_core)


def module_workflows():
    """Frontend workflow names per module, for modules exposed to the frontend."""
    return {
        definition.key: list(definition.frontend_workflows)
        for definition in MODULES
        if definition.frontend_exposed and definition.frontend_workflows
    }


def module_dependencies():
    """Module -> modules it requires."""
    return {
        definition.key: tuple(definition.requires_modules)
        for definition in MODULES
        if definition.requires_modules
    }


def is_frontend_exposed(key):
    """Whether a key may appear in the bootstrap payload.

    Unknown (legacy) keys stay exposed: `_canonical_modules` deliberately preserves
    them, so filtering them out here would silently drop a tenant's stored capability.
    """
    definition = BY_KEY.get(key)
    return True if definition is None else definition.frontend_exposed


class ImproperlyConfiguredRegistry(Exception):
    """Raised at import time when the registry itself is inconsistent."""


def _validate_registry():
    if len(BY_KEY) != len(MODULES):
        seen, duplicates = set(), set()
        for definition in MODULES:
            (duplicates if definition.key in seen else seen).add(definition.key)
        raise ImproperlyConfiguredRegistry(f"Duplicate module keys: {sorted(duplicates)}.")
    for definition in MODULES:
        unknown = [key for key in definition.requires_modules if key not in BY_KEY]
        if unknown:
            raise ImproperlyConfiguredRegistry(
                f"{definition.key} requires unknown module(s): {', '.join(unknown)}."
            )
        if definition.is_core and not definition.default_enabled:
            raise ImproperlyConfiguredRegistry(
                f"{definition.key} is core and must be enabled by default."
            )
        if definition.enforcement not in {GUARD, FEATURE_PARENT, NONE}:
            raise ImproperlyConfiguredRegistry(
                f"{definition.key} has unknown enforcement {definition.enforcement!r}."
            )


class ImproperlyConfiguredRegistry(Exception):
    """Raised at import time when the registry itself is inconsistent."""


_validate_registry()
