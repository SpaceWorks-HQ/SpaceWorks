"""The module catalogue: every ModuleDefinition, in display order.

Split out of ``module_registry`` so the registry file holds only derivation and
validation; add a module HERE. ``module_registry`` builds ``BY_KEY`` and validates
this tuple at import time, so a bad entry still fails the process at startup.
"""

from apps.makerspaces.module_registry_definitions import (
    FEATURE_PARENT,
    GROUP_BOOKINGS,
    GROUP_DEVICES,
    GROUP_EVENTS,
    GROUP_INVENTORY,
    GROUP_MACHINES,
    GROUP_MEMBERSHIP,
    GROUP_MOBILE,
    GROUP_NOTIFICATIONS,
    GROUP_PAYMENTS,
    GROUP_REPORTS,
    GROUP_STOCKTAKE,
    GROUP_UPDATES,
    GUARD,
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
        "telegram", "Telegram", "Per-makerspace Telegram group alerts (outbound only).",
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
    # NOT dependent on `membership`, deliberately. Its public submit is a PROPOSAL that
    # staff act on -- "please make this for me", not the requester operating the machine --
    # so it takes the same shape as the public borrow request: membership when that module
    # is installed, an active account otherwise. Declaring the dependency instead would
    # have dragged `membership` into the default profile and silently made ordinary
    # borrowing require a membership, waiver and presence session.
    ModuleDefinition(
        "machine_service", "Machine service", "Machine service requests and consoles.",
        "machines", GUARD, group=GROUP_MACHINES, frontend_workflows=("machine_service_requests",),
    ),
    # Requires `membership`: registration resolves through `require_active_member`, and the
    # host waiver it records lives on MakerspaceMembership. Without that module the public
    # listing renders and every registration refuses.
    ModuleDefinition(
        "events", "Events", "Event scheduling and registrations.", "events", GUARD, group=GROUP_EVENTS,
        requires_modules=("membership",),
    ),
    # Requires `membership`: public self-booking calls `require_active_member_presence`, so
    # without a MakerspaceMembership row the catalogue lists and the booking mutation dies.
    ModuleDefinition(
        "bookings", "Bookings", "Resource booking and public self-booking.", "bookings", GUARD, group=GROUP_BOOKINGS,
        requires_modules=("membership",),
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
    # Not a chat room: an HTTPS endpoint of the makerspace's own that receives every
    # notification the matrix routes to it as signed JSON. Same destination model, same
    # matrix, same retry and delivery log as the chat channels.
    ModuleDefinition(
        "webhook", "Signed webhooks",
        "Per-makerspace signed JSON webhooks to your own systems.",
        "integrations", GUARD, group=GROUP_NOTIFICATIONS,
    ),
    # These keys were placed in front of substrate that had been unconditionally
    # present, so migration 0057 backfilled their original keys onto existing rows.
    # Updates remains default-enabled; member accounts, mobile and now payments are
    # opt-in for newly created makerspaces.
    # `payments` stopped being default-enabled when charge TRACKING moved out from under
    # it (`charges.*`): the module now buys only the online rail, which a cash-taking
    # space needs none of. Existing rows keep the key from migration 0057.
    ModuleDefinition(
        "payments", "Payments",
        "Online card payment (Stripe/Razorpay). Money owed is tracked without it.",
        "payments_rail", GUARD, group=GROUP_PAYMENTS,
    ),
    # Member-facing identity only. Staff authentication is core RBAC and is NEVER gated:
    # a space that could switch off its own staff logins could not be administered, the
    # same reasoning that keeps the staff roster ungated by `membership` (plan A7).
    ModuleDefinition(
        "member_accounts", "Member accounts",
        "Member self-service enrolment and built-in password, social and phone login. "
        "Staff sign-in, external identity and member-domain APIs are unaffected.",
        "accounts", GUARD, group=GROUP_MEMBERSHIP,
    ),
    # Requires `member_accounts` because a device grant is bound to a user: without
    # member accounts there is no identity for a phone to hold.
    ModuleDefinition(
        "mobile", "Mobile apps",
        "Attested device sessions, native push and the in-app payment sheet.",
        "accounts", GUARD, group=GROUP_MOBILE,
        requires_modules=("member_accounts",),
    ),
    # Opt-in and dependency-free: device identity is a trust boundary that printer and
    # label adapters build on, so it must not force `machines` onto a label-only space.
    # Each later adapter guards its own module instead of widening this tuple.
    ModuleDefinition(
        "devices", "Connected devices",
        "Enrolled printers and label printers that authenticate with an Ed25519 key.",
        "devices", GUARD, group=GROUP_DEVICES,
    ),
    ModuleDefinition(
        "updates", "Updates", "In-app platform release checks and controlled updates.",
        "updates", GUARD, group=GROUP_UPDATES, default_enabled=True,
    ),
)
