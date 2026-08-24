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
GROUP_PAYMENTS = "payments"
GROUP_ACCOUNTS = "accounts"
GROUP_MOBILE = "mobile"
GROUP_UPDATES = "updates"


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
    GroupDefinition(
        GROUP_PAYMENTS, "Payments",
        "Taking money online for machine jobs, bookings, event registrations and "
        "membership dues.",
    ),
    GroupDefinition(
        GROUP_ACCOUNTS, "Accounts",
        "The member-facing identity ecosystem: self sign-up, social and phone login, "
        "and the member area. Staff always sign in with a password regardless.",
    ),
    GroupDefinition(
        GROUP_MOBILE, "Mobile apps",
        "Attested device sessions, native push and the in-app payment sheet.",
    ),
    GroupDefinition(
        GROUP_UPDATES, "Updates",
        "In-app release control. A deployment updated by its own host tooling ships "
        "none of it.",
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
