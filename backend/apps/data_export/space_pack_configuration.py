"""Reviewed CONFIGURATION projection, deliberately separate from tenant exports.

The tenant-export catalogue includes personal and operational records. Packs must
never reuse its datasets. These literal subsets are the only pack source fields;
relations are emitted as local names, never database IDs. Prices here are policy
defaults, not debts, payments, settlements or member balances.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class PackSection:
    model: str
    fields: tuple[str, ...]
    identity: tuple[str, ...] = ()
    module: str | None = None
    action: str = "manage_makerspace"


def section(model, fields, identity="", module=None, action="manage_makerspace"):
    return PackSection(model, tuple(fields.split()), tuple(identity.split()), module, action)


SETTINGS_FIELDS = tuple("""public_inventory_enabled public_site_enabled public_landing_page public_stats_enabled
public_stats_show_holder_names public_print_status_lookup_policy membership_policy
membership_dues_amount referrals_enabled lapsed_members_cannot_borrow
staff_notifications_enabled booking_requester_notifications_enabled
default_loan_days presence_preset_minutes""".split())
HOURS_FIELDS = ("timezone", "opening_hours")

SECTIONS = {
    "roles": section("makerspaces.MakerspaceRole", "name granted_actions", "name"),
    "active_waiver": section("makerspaces.MakerspaceWaiver", "version body"),
    "loan_policy": section("makerspaces.MakerspaceLoanPolicy", """default_loan_days
        loan_renewal_mode loan_max_renewals loan_renewal_days loan_max_active loan_max_items
        loan_reminder_offsets_hours loan_escalate_overdue_days""", module="request_workflow"),
    "membership_plans": section("makerspaces.MembershipPlan", """name interval custom_days
        amount currency is_active loan_max_active loan_max_items""", "name", "membership"),
    "admission_policy": section("makerspaces.MakerspaceMembershipSettings", """join_mode
        vouches_required voucher_min_tenure_days voucher_pending_limit vouch_expiry_days
        vouch_replaces_approval payment_timing application_schema default_plan joining_fee
        joining_fee_currency rejoin_dues_rule request_expiry_days""", module="membership"),
    "booking_rules": section("bookings.BookableSpace", """name min_booking_duration_minutes
        max_booking_duration_minutes booking_lead_time_minutes max_booking_advance_days
        approval_mode""", "name", "bookings", "manage_bookings"),
    "notification_defaults": section("integrations.NotificationPreference",
        "feature channel enabled", "feature channel"),
    "email_mutes": section("integrations.EmailNotificationMute",
        "target stream event audience", "target stream event"),
    "email_templates": section("integrations.EmailTemplate",
        "stream audience key subject text_body html_body is_active", "stream audience key", "email"),
    "chat_templates": section("integrations.ChatTemplate",
        "feature event text_body is_active", "feature event", "notifications"),
    "categories": section("inventory.Category", "slug name display_order icon loan_days max_renewals",
        "slug", "public_inventory", "edit_inventory"),
    "item_templates": section("inventory.InventoryProduct", """name category description
        tracking_mode loan_days max_renewals is_public public_self_checkout_enabled
        show_public_count public_availability_mode""", "name", "public_inventory", "edit_inventory"),
}

# These two models are omitted from tenant dumps because they govern live delivery.
# Packs explicitly carry the space-wide matrix/mutes only: no destinations,
# recipients, member preferences, tokens, URLs or scope bindings.
PACK_ONLY_CONFIGURATION_MODELS = frozenset({
    "integrations.NotificationPreference", "integrations.EmailNotificationMute",
})


def assert_pack_classification():
    """Fail closed if a section drifts beyond its reviewed configuration subset."""
    from .classification import EXPORTED_MODEL_FIELDS, OMITTED_MODELS

    for spec in SECTIONS.values():
        if spec.model in PACK_ONLY_CONFIGURATION_MODELS:
            assert spec.model in OMITTED_MODELS
        else:
            assert set(spec.fields) <= set(EXPORTED_MODEL_FIELDS[spec.model].split())
    assert set(SETTINGS_FIELDS + HOURS_FIELDS) <= set(
        EXPORTED_MODEL_FIELDS["makerspaces.Makerspace"].split()
    )
