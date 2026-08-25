"""Canonical registry of makerspace modules.

Single source of truth for module keys, their defaults, frontend exposure and
inter-module dependencies. The parallel hand-kept lists that used to drift apart
-- ``models.DEFAULT_ENABLED_MODULES``, ``platform.MODULE_WORKFLOWS``,
``capabilities.FEATURE_MODULES`` and the hardcoded ``printing -> machine_service``
rule -- all derive from here now.

This module must NOT import ``apps.makerspaces.models``. ``models`` imports the
derived helpers from here, so the reverse edge would be a circular import.
"""

from apps.makerspaces.module_registry_definitions import (
    FEATURE_PARENT,
    GROUP_ACCOUNTS,
    GROUP_BOOKINGS,
    GROUP_EVENTS,
    GROUP_INVENTORY,
    GROUP_KEYS,
    GROUP_MACHINES,
    GROUP_MEMBERSHIP,
    GROUP_MOBILE,
    GROUP_NOTIFICATIONS,
    GROUP_PAYMENTS,
    GROUP_REPORTS,
    GROUP_STOCKTAKE,
    GROUP_UPDATES,
    GROUPS,
    GROUPS_BY_KEY,
    GUARD,
    NONE,
    GroupDefinition,
    ModuleDefinition,
)


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
    # Community enrolment/content. Identity may instead come from external OIDC or a
    # staff-created person record, so this deliberately does not depend on
    # `member_accounts`.
    ModuleDefinition(
        "membership", "Membership",
        "Join requests, referrals, verification, profiles, directory and member activity.",
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
    # These keys were placed in front of substrate that had been unconditionally
    # present, so migration 0057 backfilled their original keys onto existing rows.
    # Payments and updates remain default-enabled; member accounts and mobile are now
    # opt-in for newly created makerspaces.
    ModuleDefinition(
        "payments", "Payments", "Online payment for machine jobs, bookings, events and dues.",
        "payments", GUARD, group=GROUP_PAYMENTS, default_enabled=True,
    ),
    # Member-facing identity only. Staff authentication is core RBAC and is NEVER gated:
    # a space that could switch off its own staff logins could not be administered, the
    # same reasoning that keeps the staff roster ungated by `membership` (plan A7).
    ModuleDefinition(
        "member_accounts", "Member accounts",
        "Member self-service enrolment and built-in password, social and phone login. "
        "Staff sign-in, external identity and member-domain APIs are unaffected.",
        "accounts", GUARD, group=GROUP_ACCOUNTS,
    ),
    # Requires `member_accounts` because a device grant is bound to a user: without
    # member accounts there is no identity for a phone to hold.
    ModuleDefinition(
        "mobile", "Mobile apps",
        "Attested device sessions, native push and the in-app payment sheet.",
        "accounts", GUARD, group=GROUP_MOBILE,
        requires_modules=("member_accounts",),
    ),
    ModuleDefinition(
        "updates", "Updates", "In-app platform release checks and controlled updates.",
        "updates", GUARD, group=GROUP_UPDATES, default_enabled=True,
    ),
)

BY_KEY = {definition.key: definition for definition in MODULES}
MODULE_KEYS = frozenset(BY_KEY)


from apps.makerspaces import module_registry_helpers as _registry_helpers  # noqa: E402

_registry_helpers.BY_KEY = BY_KEY
_registry_helpers.GROUPS = GROUPS
_registry_helpers.GROUPS_BY_KEY = GROUPS_BY_KEY
_registry_helpers.MODULES = MODULES

from apps.makerspaces.module_registry_helpers import (  # noqa: E402
    core_module_keys,
    default_enabled_module_keys,
    dependents_of,
    group_for,
    group_is_always_on,
    group_module_keys,
    is_frontend_exposed,
    module_available,
    module_dependencies,
    module_workflows,
    modules_by_group,
    with_dependencies,
)


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
