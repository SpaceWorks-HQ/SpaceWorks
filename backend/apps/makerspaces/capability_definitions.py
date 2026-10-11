"""Canonical makerspace module and feature capability definitions."""

from dataclasses import dataclass

from apps.makerspaces.module_registry import MODULE_KEYS

from .capability_definitions_modules import module_family_features
from .capability_definitions_w7_events import event_features


@dataclass(frozen=True)
class FeatureDefinition:
    key: str
    # None => standalone feature with no parent-module prerequisite (effective purely
    # when enabled). Used for capabilities that are not a child of any single module,
    # e.g. self-checkout / direct handouts, which a private makerspace runs without a
    # public catalogue. A string parent must be a registered module key.
    parent_module: str | None
    label: str
    description: str = ""
    default_enabled: bool = False
    requires_modules: tuple[str, ...] = ()
    requires_features: tuple[str, ...] = ()
    frontend_exposed: bool = True


FEATURE_DEFINITIONS = (
    FeatureDefinition("packs.import", "staff_admin", "Space packs",
                      "Export and apply configuration-only packs with a diff preview."),
    FeatureDefinition("membership.auto_renew", "membership", "Automatic membership renewal"),
    FeatureDefinition("membership.lifecycle_mail", "membership", "Membership lifecycle mail"),
    FeatureDefinition("membership.self_service", "membership", "Member account self-service"),
    FeatureDefinition("membership.self_export", "membership", "Member data export"),
    FeatureDefinition("reports.saved_views", "reports", "Saved report views",
                      "Save personal report filters and publish makerspace views.", default_enabled=True),
    FeatureDefinition("billing.documents", None, "Receipt documents",
                      "Numbered receipts and credit notes from the core ledger.", default_enabled=True),
    FeatureDefinition(
        "notifications.member_inbox", "notifications", "Member inbox",
        "Personal lifecycle messages and read state for members.", default_enabled=False,
    ),
    FeatureDefinition(
        "notifications.member_preferences", "notifications", "Member communication preferences",
        "Members can mute optional families per personal channel; safety mail stays on.",
        default_enabled=False,
    ),
    FeatureDefinition("billing.reminders", "notifications", "Payment reminders",
                      "Email the payer about due and overdue charges, including cash-only charges."),
    FeatureDefinition("loans.renewals", "request_workflow", "Loan renewals",
                      "Allow policy-bound extensions of issued loans."),
    FeatureDefinition("loans.limits", "request_workflow", "Borrow limits",
                      "Limit active loans and outstanding items per borrower."),
    FeatureDefinition("loans.kit_checklist", "containers", "Kit checklists",
                      "Count kit components at issue and return; retain missing-component accountability."),
    FeatureDefinition("staff.invitations", None, "Staff invitations",
                      "Invite staff with a single-use email link.", default_enabled=True),
    FeatureDefinition("security.staff_mfa_required", None, "Require MFA for staff",
                      "Require staff with actions in this space to enroll in TOTP MFA."),
    FeatureDefinition("membership.vouching", "membership", "Membership vouching",
                      "Require eligible members to vouch before admission."),
    FeatureDefinition("membership.application_form", "membership", "Membership application form",
                      "Collect private answers on community join requests."),
    FeatureDefinition(
        "payments.machines", "machines", "Machine payments",
        "Charge for machine service requests via Stripe.",
        requires_modules=("machine_service", "payments"),
    ),
    FeatureDefinition(
        "payments.bookings", "bookings", "Booking payments",
        "Charge for resource bookings via Stripe.",
        requires_modules=("payments",),
    ),
    FeatureDefinition(
        "payments.events", "events", "Event payments",
        "Charge for event registrations via Stripe.",
        requires_modules=("payments",),
    ),
    FeatureDefinition(
        "payments.membership", "membership", "Membership payments",
        "Charge membership dues via Stripe.",
        requires_modules=("payments",),
    ),
    FeatureDefinition(
        "payments.loans", "payments", "Loan deposits and late fees",
        "Raise a deposit when a reviewed loan is issued and a capped late fee when it "
        "comes back after its due date; both settle through the same payment rails.",
        default_enabled=False,
    ),
    # --- Charge tracking (money owed) -------------------------------------------------
    # Deliberately NOT dependent on the `payments` module. Recording what a member owes
    # and collecting it online are different capabilities: a space that takes cash still
    # needs the debt on its books, visible in the member area, settleable by staff and
    # counted in reports. The `payments.*` family above stays the ONLINE-RAIL capability
    # set and keeps its `payments` module dependency; these govern whether a charge is
    # recorded at all.
    #
    # Each keeps its real DOMAIN dependency -- there is no point tracking booking money
    # in a space with no bookings -- but never a payments one. `charges.enabled` is the
    # standalone master switch, and a space that charges for nothing simply turns it off.
    # It is NOT expressed as `requires_features` on the domain keys: that would make the
    # kill switch un-flippable until every domain was unticked first (the A6 rule).
    FeatureDefinition(
        "charges.enabled", None, "Track money owed",
        "Record what members owe for bookings, events, machine jobs, dues and loans -- "
        "whether or not online payment is configured. Off means the space charges for "
        "nothing.",
        default_enabled=True,
    ),
    FeatureDefinition(
        "charges.bookings", "bookings", "Track booking charges",
        "Record a charge when a paid booking is confirmed.",
        default_enabled=True,
    ),
    FeatureDefinition(
        "charges.events", "events", "Track event charges",
        "Record a charge when a member registers for a paid event.",
        default_enabled=True,
    ),
    FeatureDefinition(
        "charges.machines", "machines", "Track machine job charges",
        "Record a charge when a priced machine service request completes.",
        default_enabled=True,
        requires_modules=("machine_service",),
    ),
    FeatureDefinition(
        "charges.membership", "membership", "Track membership charges",
        "Record dues and renewal charges for members.",
        default_enabled=True,
    ),
    FeatureDefinition(
        "charges.loans", "request_workflow", "Track loan charges",
        "Record loan deposits and late fees. Parented to the core request workflow, so "
        "it never drags the payments module into lending.",
        default_enabled=True,
    ),
    FeatureDefinition(
        "inventory.self_checkout", None, "Self checkout",
        "Member self-checkout and staff direct handouts of QR tools.",
        default_enabled=True,
    ),
    # The three below are standalone master switches (plan A6). Each is an additive
    # `AND` in front of an existing readiness check, never a replacement -- turning one
    # ON must not make an unconfigured capability start working. They default ENABLED so
    # that adding them changes nothing for a makerspace that was already using the
    # capability; migration 0051 backfills the same keys onto rows that predate them.
    # Parented to the `payments` MODULE (phase 3). The module removes the surfaces; this
    # feature is the space manager's own kill switch in front of a module that is
    # installed. Both are additive ANDs -- turning either ON still cannot make an
    # unconfigured provider start charging.
    FeatureDefinition(
        "payments.enabled", "payments", "Payments",
        "Master switch for online payments; each domain still needs its own "
        "payments.* feature and configured credentials.",
        default_enabled=True,
    ),
    FeatureDefinition(
        "mobile.push", "mobile", "Native push",
        "Native push notifications to this makerspace's registered devices; still "
        "requires platform FCM/APNs credentials.",
        default_enabled=True,
    ),
    FeatureDefinition(
        "presence.geofence", None, "Presence geofence",
        "Advisory proximity classification on check-in; still requires the makerspace "
        "geofence to be configured. Never an access gate.",
        default_enabled=True,
    ),
    FeatureDefinition(
        "notifications.delegated_recipients", "notifications",
        "Delegated maintenance recipients",
        "Let machine-scoped maintainers manage maintenance alert recipients for "
        "their own machines.",
        default_enabled=False,
        # It delegates MAINTENANCE alerts, narrowed by MACHINE scope, so it cannot function
        # without either module. Declaring only `notifications` let capability validation
        # accept an unusable combination, and -- worse -- uninstalling `maintenance` or
        # `machines` did not prune the enabled feature, so reinstalling silently
        # reactivated delegated access without anybody opting in again.
        requires_modules=("maintenance", "machines"),
    ),
    FeatureDefinition(
        "machines.certifications", "machines", "Certification gating",
        "Members must hold an unexpired certification for a machine type before "
        "booking it or requesting work on it.",
        default_enabled=False,
    ),
    FeatureDefinition(
        "machines.certification_reminders", "machines", "Certification reminders",
        "Send member expiry notices and a scoped staff digest.",
        requires_modules=("notifications",),
    ),
    FeatureDefinition(
        "maintenance.reminders", "maintenance", "Maintenance reminders",
        "Notify scoped maintainers before and after maintenance is due.",
        requires_modules=("machines", "notifications"),
    ),
    FeatureDefinition(
        "events.offline_checkin", "events", "Offline & station check-in",
        "Store a minimal expiring roster on event devices and enable event-scoped "
        "PIN stations.",
        default_enabled=False,
    ),
    FeatureDefinition(
        "inventory.kiosk", None, "Kiosk",
        "Scanner and handover Stations: a Station PIN opens the channel and a signed-in "
        "staff operator lease attributes every handover to a real person.",
        default_enabled=False,
    ),
)
FEATURE_DEFINITIONS += event_features(FeatureDefinition)
FEATURE_DEFINITIONS += module_family_features(FeatureDefinition)
FEATURES = {definition.key: definition for definition in FEATURE_DEFINITIONS}
# A feature's parent/required modules are validated against the module registry
# rather than a hand-kept set, so adding a module can no longer leave a valid
# parent silently unrecognised (which would disable the feature).
FEATURE_MODULES = MODULE_KEYS

