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


# Operator-facing grouping. The module keys below stay the enforcement primitives --
# every `require_module` call site, every stored `enabled_modules` row and the drift
# guard are untouched by this layer. A group is only what the console *shows*, so an
# operator picks from a handful of switches instead of nearly thirty keys.
#
# Collapsing the keys into nine real modules was the alternative and was rejected: it
# would have meant rewriting every call site and migrating every tenant's stored JSON,
# where a key that failed to migrate reads as *off* and silently removes surfaces from a
# live makerspace. This gets the same operator experience with none of that risk, and it
# is what keeps "add a module later" a one-entry change.
GROUP_INVENTORY = "inventory"
GROUP_STOCKTAKE = "stocktake"
GROUP_MACHINES = "machines"
GROUP_EVENTS = "events"
GROUP_BOOKINGS = "bookings"
GROUP_MEMBERSHIP = "membership"
GROUP_NOTIFICATIONS = "notifications"
GROUP_REPORTS = "reports"


@dataclass(frozen=True)
class GroupDefinition:
    key: str
    label: str
    description: str
    # Inventory is a permanent heading rather than a switch: it absorbs the six core
    # keys, and core exists because the Hard Rules make the loan spine *the system* --
    # issuing hardware requires a box QR scan AND an issue photo.
    always_on: bool = False


GROUPS = (
    GroupDefinition(
        GROUP_INVENTORY, "Inventory",
        "The hardware catalogue, request workflow, QR/evidence spine and everything "
        "that moves stock. Always on.",
        always_on=True,
    ),
    GroupDefinition(
        GROUP_STOCKTAKE, "Stocktake", "Scan-first stock counts and variance reporting.",
    ),
    GroupDefinition(
        GROUP_MACHINES, "Machines",
        "Machine registry, the service/print queue and preventive maintenance. "
        "Warranty tracking for machines lives here too.",
    ),
    GroupDefinition(GROUP_EVENTS, "Events", "Event scheduling and registrations."),
    GroupDefinition(GROUP_BOOKINGS, "Bookings", "Resource booking and public self-booking."),
    GroupDefinition(
        GROUP_MEMBERSHIP, "Membership",
        "Community membership: join requests, waivers, referrals, member activity and "
        "presence check-in.",
    ),
    GroupDefinition(
        GROUP_NOTIFICATIONS, "Notifications",
        "The in-app inbox and every outbound channel: email, Telegram, Slack, "
        "Mattermost and Discord. API-client issuance sits here.",
    ),
    GroupDefinition(
        GROUP_REPORTS, "Reports",
        "Analytics, the report registry and CSV/XLSX exports. Standalone rather than "
        "part of Inventory, because switching Inventory off would otherwise kill the "
        "machine and event reports too.",
    ),
)

GROUPS_BY_KEY = {group.key: group for group in GROUPS}
GROUP_KEYS = frozenset(GROUPS_BY_KEY)


@dataclass(frozen=True)
class ModuleDefinition:
    key: str
    label: str
    description: str
    app_label: str
    enforcement: str
    # The operator-facing heading this key sits under. Deliberately has NO default: a
    # module that forgets it would silently vanish from the console it is meant to be
    # administered from, so `_validate_registry` refuses the registry instead.
    group: str
    # Modules that must also be enabled for this one to be valid. Replaces the
    # hardcoded printing -> machine_service branch in `validate_capabilities`.
    requires_modules: tuple[str, ...] = ()
    # Modules are opt-in: a new makerspace installs core plus whatever profile the
    # operator chose. Core modules are always on and need not set this.
    default_enabled: bool = False
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
        "inventory", GUARD, group=GROUP_INVENTORY, is_core=True, frontend_workflows=("catalog",),
    ),
    ModuleDefinition(
        "request_workflow", "Request workflow", "Member hardware requests and their status.",
        "hardware_requests", GUARD, group=GROUP_INVENTORY, is_core=True,
        frontend_workflows=("request_submit", "request_status"),
    ),
    ModuleDefinition(
        "staff_admin", "Staff admin", "Staff console inventory and request administration.",
        "admin_api", GUARD, group=GROUP_INVENTORY, is_core=True,
        frontend_workflows=("staff_inventory", "staff_requests"),
    ),
    ModuleDefinition(
        "guest_handover", "Guest handover", "Guest admin issue and return of accepted requests.",
        "hardware_requests", GUARD, group=GROUP_INVENTORY, frontend_workflows=("guest_issue", "guest_return"),
    ),
    ModuleDefinition(
        "scanner", "Scanner", "QR scanning and container lookup.",
        "boxes", GUARD, group=GROUP_INVENTORY, is_core=True, frontend_workflows=("qr_scan", "container_lookup"),
    ),
    ModuleDefinition(
        "printing", "Printing", "3D print request queue (a machine type under `machines`).",
        "machines", GUARD, group=GROUP_MACHINES, requires_modules=("machine_service",),
        frontend_workflows=("printing_requests",),
    ),
    ModuleDefinition(
        "telegram", "Telegram", "Per-makerspace Telegram group alerts and callbacks.",
        "integrations", GUARD, group=GROUP_NOTIFICATIONS, frontend_workflows=("telegram_alerts",),
    ),
    ModuleDefinition(
        "evidence_uploads", "Evidence uploads", "Immutable issue and return evidence photos.",
        "evidence", GUARD, group=GROUP_INVENTORY, is_core=True, frontend_workflows=("evidence_uploads",),
    ),
    ModuleDefinition(
        "qr_management", "QR management", "QR generation, revocation and printing.",
        "boxes", GUARD, group=GROUP_INVENTORY, is_core=True,
        frontend_workflows=("qr_generate", "qr_revoke", "qr_print"),
    ),
    ModuleDefinition(
        "bulk_import", "Bulk import", "Spreadsheet import of inventory rows.",
        "admin_api", GUARD, group=GROUP_INVENTORY, frontend_workflows=("bulk_import",),
    ),
    ModuleDefinition(
        "containers", "Containers", "Physical container hierarchy and moves.",
        "operations", GUARD, group=GROUP_INVENTORY, frontend_workflows=("container_lookup", "container_move"),
    ),
    ModuleDefinition(
        "stock_transfers", "Stock transfers", "Intra- and cross-makerspace stock movement.",
        "operations", GUARD, group=GROUP_INVENTORY, frontend_workflows=("stock_transfer",),
    ),
    ModuleDefinition(
        "stocktake", "Stocktake", "Scan-first stocktake sessions and variance.",
        "operations", GUARD, group=GROUP_STOCKTAKE, frontend_workflows=("stocktake",),
    ),
    ModuleDefinition(
        "reports", "Reports", "Analytics, report registry and CSV/XLSX exports.",
        "operations", GUARD, group=GROUP_REPORTS, frontend_workflows=("analytics", "report_export"),
    ),
    ModuleDefinition(
        "qr_print_batches", "QR print batches", "Batched QR label ZIP generation.",
        "operations", GUARD, group=GROUP_INVENTORY, frontend_workflows=("qr_print_batch",),
    ),
    ModuleDefinition(
        "asset_units", "Asset units", "Individually QR-tracked asset units.",
        "inventory", GUARD, group=GROUP_INVENTORY, frontend_workflows=("asset_qr_generation",),
    ),
    ModuleDefinition(
        "procurement", "Procurement", "To-buy list and procurement tracking.",
        "procurement", GUARD, group=GROUP_INVENTORY, frontend_workflows=("procurement",),
    ),
    ModuleDefinition(
        "machines", "Machines", "Machine registry, operators, usage and documents.",
        "machines", GUARD, group=GROUP_MACHINES,
    ),
    ModuleDefinition(
        "machine_service", "Machine service", "Machine service requests and consoles.",
        "machines", GUARD, group=GROUP_MACHINES, frontend_workflows=("machine_service_requests",),
    ),
    ModuleDefinition(
        "events", "Events", "Event scheduling and registrations.", "events", GUARD, group=GROUP_EVENTS,
    ),
    ModuleDefinition(
        "bookings", "Bookings", "Resource booking and public self-booking.", "bookings", GUARD, group=GROUP_BOOKINGS,
    ),
    ModuleDefinition(
        "maintenance", "Maintenance", "Maintenance schedules and work orders.",
        "maintenance", GUARD, group=GROUP_MACHINES, frontend_workflows=("maintenance",),
    ),
    ModuleDefinition(
        "membership", "Membership", "Community membership, waivers and referrals.",
        "makerspaces", FEATURE_PARENT, group=GROUP_MEMBERSHIP,
    ),
    # Enforced by apps/notifications, but historically absent from the defaults list --
    # which is why the /control/ matrix (choices = defaults + keys already on the row)
    # can never offer it on a new makerspace. Registering it here makes it known;
    # sourcing the admin choices from this registry is the actual fix (phase 3).
    ModuleDefinition(
        "notifications", "Notifications", "In-app notification inbox and emitters.",
        "notifications", GUARD, group=GROUP_NOTIFICATIONS,
    ),
    # Tenant email delivery only. Account recovery and email verification are platform
    # mail (`makerspace=None`) and are NOT this module's to disable -- see
    # `integrations.dispatch.EMAIL_MODULE_EXEMPT`.
    ModuleDefinition(
        "email", "Email", "Outbound email delivery for this makerspace.",
        "integrations", GUARD, group=GROUP_NOTIFICATIONS,
    ),
    # One module key per notification channel, so a makerspace ships only the channels
    # it actually uses. `telegram` and `email` above are the same idea and predate these;
    # these three complete the set. All are `integrations`-owned and independently
    # switchable -- a space on Discord alone should carry no Slack surface at all.
    #
    # Each is an additive AND in front of the credential check that already existed:
    # turning a key ON can never make an unconfigured channel start sending, and turning
    # it OFF stops sending even though the webhook is still stored (so re-enabling needs
    # no re-entry of the credential).
    ModuleDefinition(
        "slack", "Slack", "Per-makerspace Slack incoming-webhook alerts.",
        "integrations", GUARD, group=GROUP_NOTIFICATIONS,
    ),
    ModuleDefinition(
        "mattermost", "Mattermost", "Per-makerspace Mattermost incoming-webhook alerts.",
        "integrations", GUARD, group=GROUP_NOTIFICATIONS,
    ),
    ModuleDefinition(
        "discord", "Discord", "Per-makerspace Discord incoming-webhook alerts.",
        "integrations", GUARD, group=GROUP_NOTIFICATIONS,
    ),
)

BY_KEY = {definition.key: definition for definition in MODULES}
MODULE_KEYS = frozenset(BY_KEY)


def default_enabled_module_keys():
    """Enabled-by-default module keys for a new makerspace (a fresh list every call).

    Core is always included; everything else is opt-in and arrives via an install
    profile or `install_module`.

    Returned fresh because this backs a JSONField default: handing out the registry's
    own collection would let one makerspace's row mutate every future default.
    """
    return [
        definition.key
        for definition in MODULES
        if definition.default_enabled or definition.is_core
    ]


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


def modules_by_group():
    """Group key -> the modules under it, in registry order.

    The console renders this: one heading per group, the keys underneath. Returned
    fresh, and built from ``GROUPS`` rather than from the modules, so a group with no
    modules still appears (and so the order is the declared one, not hash order).
    """
    grouped = {group.key: [] for group in GROUPS}
    for definition in MODULES:
        grouped[definition.group].append(definition)
    return grouped


def group_for(key):
    """The group a module key belongs to, or ``None`` for an unknown legacy key.

    Unknown keys have no group for the same reason they stay frontend-exposed:
    ``_canonical_modules`` preserves them, and inventing a group would file a tenant's
    stored capability under a heading the registry knows nothing about.
    """
    definition = BY_KEY.get(key)
    return None if definition is None else definition.group


def group_module_keys(group_key):
    """Every module key under a group, core included."""
    return tuple(
        definition.key for definition in MODULES if definition.group == group_key
    )


def group_is_always_on(group_key):
    """Whether a group may be switched off at all.

    A group is always on when it is declared so, and also whenever it contains a core
    key -- the console must not offer a master toggle that ``_canonical_modules`` would
    silently undo by adding core back on the next write.
    """
    group = GROUPS_BY_KEY.get(group_key)
    if group is None:
        return False
    if group.always_on:
        return True
    return any(BY_KEY[key].is_core for key in group_module_keys(group_key))


def module_dependencies():
    """Module -> modules it requires."""
    return {
        definition.key: tuple(definition.requires_modules)
        for definition in MODULES
        if definition.requires_modules
    }


def with_dependencies(keys):
    """Expand keys to include everything they transitively require.

    Installing `printing` must pull in `machine_service`, or the install immediately
    fails the very dependency rule the registry declares.
    """
    resolved, queue = set(), list(keys)
    while queue:
        key = queue.pop()
        if key in resolved:
            continue
        resolved.add(key)
        definition = BY_KEY.get(key)
        if definition is not None:
            queue.extend(definition.requires_modules)
    return resolved


def dependents_of(key, among):
    """Which of `among` require `key` -- i.e. what breaks if `key` is removed."""
    return sorted(
        candidate
        for candidate in among
        if candidate in BY_KEY and key in BY_KEY[candidate].requires_modules
    )


def module_available(key):
    """Whether the app owning this module ships runtime surfaces in this deployment.

    Orthogonal to per-makerspace enablement, and deliberately not merged with it: a
    tombstoned app's key stays in a tenant's stored `enabled_modules` (uninstall
    retains data and is reversible, and a deployment-level decision must not rewrite
    tenant rows), but nothing the key names is reachable, so every consumer has to
    read it as off.

    Unknown legacy keys have no owning app and stay available, for the same reason
    `is_frontend_exposed` keeps them: filtering them out would silently drop a
    capability the registry has not learned about yet.
    """
    from apps.separability.registry import runtime_active

    definition = BY_KEY.get(key)
    return True if definition is None else runtime_active(definition.app_label)


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
        if definition.is_core and definition.default_enabled:
            raise ImproperlyConfiguredRegistry(
                f"{definition.key} is core, which already implies default_enabled."
            )
        if definition.enforcement not in {GUARD, FEATURE_PARENT, NONE}:
            raise ImproperlyConfiguredRegistry(
                f"{definition.key} has unknown enforcement {definition.enforcement!r}."
            )
        if definition.group not in GROUP_KEYS:
            raise ImproperlyConfiguredRegistry(
                f"{definition.key} declares unknown group {definition.group!r}. "
                f"Known groups: {', '.join(sorted(GROUP_KEYS))}."
            )
    if len(GROUPS_BY_KEY) != len(GROUPS):
        raise ImproperlyConfiguredRegistry("Duplicate group keys.")
    for group in GROUPS:
        if not group.label or not group.description:
            raise ImproperlyConfiguredRegistry(f"Group {group.key} needs a label and description.")
        # An empty group renders as a heading an operator can click with nothing behind
        # it, which reads as a broken install rather than an unused one.
        if not group_module_keys(group.key):
            raise ImproperlyConfiguredRegistry(f"Group {group.key} contains no modules.")
    # A group declared always-on must actually be un-switchable, or the console would
    # offer a master toggle whose "off" position `_canonical_modules` immediately undoes.
    for group in GROUPS:
        if group.always_on and not any(BY_KEY[key].is_core for key in group_module_keys(group.key)):
            raise ImproperlyConfiguredRegistry(
                f"Group {group.key} claims always_on but holds no core module."
            )


_validate_registry()
