"""Independent target projection values, including the intended merged opt-ins.

Callables explicitly pin generated credentials and the current revocation time;
all static values are literals rather than being copied from production registries.
"""

import secrets

from django.utils import timezone

from apps.makerspaces.models import Makerspace, MakerspaceMembership


EXPECTED_TARGET_VALUES = {
    ("operations.SavedView", "shared"): False,
    ("operations.SavedView", "state"): {},
    ("makerspaces.MakerspaceMembershipSettings", "join_mode"): "approval",
    ("makerspaces.MakerspaceMembershipSettings", "vouch_replaces_approval"): False,
    ("makerspaces.MembershipRequest", "state"): "canceled",
    ("makerspaces.MembershipRequest", "admission_managed"): False,
    ("payments.MakerspaceBillingSettings", "reminder_days_before"): [],
    ("payments.MakerspaceBillingSettings", "reminder_days_after"): [],
    ("payments.MakerspaceBillingSettings", "max_reminders"): 0,
    ("makerspaces.Makerspace", "frontend_domain"): None,
    ("makerspaces.Makerspace", "frontend_domain_status"): Makerspace.DomainStatus.PENDING,
    ("makerspaces.Makerspace", "domain_verified_at"): None,
    ("makerspaces.Makerspace", "frontend_domain_changed_at"): None,
    ("makerspaces.Makerspace", "hidden_from_central_directory"): False,
    ("makerspaces.Makerspace", "superadmin_access_enabled"): True,
    ("makerspaces.Makerspace", "archived_at"): None,
    ("makerspaces.Makerspace", "resource_limit_overrides"): {},
    ("makerspaces.Makerspace", "storage_bytes_used"): 0,
    ("makerspaces.Makerspace", "membership_policy"): Makerspace.MembershipPolicy.REQUEST,
    ("makerspaces.Makerspace", "referrals_enabled"): False,
    ("makerspaces.Makerspace", "telegram_group_chat_id"): "",
    ("makerspaces.Makerspace", "smtp_host"): "",
    ("makerspaces.Makerspace", "smtp_port"): 587,
    ("makerspaces.Makerspace", "smtp_username"): "",
    ("makerspaces.Makerspace", "smtp_use_tls"): True,
    ("makerspaces.Makerspace", "smtp_use_ssl"): False,
    ("makerspaces.Makerspace", "enabled_modules"): [
        "public_inventory", "request_workflow", "staff_admin", "scanner",
        "evidence_uploads", "qr_management", "backup", "updates",
    ],
    ("makerspaces.Makerspace", "enabled_features"): [
        "reports.saved_views", "billing.documents", "staff.invitations",
        "charges.enabled", "charges.bookings", "charges.events", "charges.machines",
        "charges.membership", "charges.loans", "inventory.self_checkout",
        "payments.enabled", "mobile.push", "presence.geofence", "loans.enabled",
    ],
    ("makerspaces.MakerspaceMembership", "receives_notifications"): True,
    ("makerspaces.MakerspaceMembership", "role"): MakerspaceMembership.Role.CUSTOM,
    ("makerspaces.MakerspaceMembership", "can_refer"): True,
    ("makerspaces.MakerspaceMembership", "can_verify"): False,
    ("makerspaces.MembershipRequest", "auto_activate_on_claim"): False,
    ("makerspaces.Station", "created_by"): None,
    ("machines.MachineType", "managing_action"): "",
    ("integrations.NotificationDestination", "is_active"): False,
    ("evidence.EvidenceRetentionPolicy", "abandoned_upload_cleanup_enabled"): False,
    ("evidence.EvidenceRetentionPolicy", "abandoned_upload_retention_days"): None,
    ("evidence.EvidencePhoto", "consumption_state"): "legacy_unknown",
    # Phase 7a: an imported device carries no live authority until the target re-enrolls it.
    ("devices.Device", "status"): "pending",
    ("devices.Device", "last_seen_at"): None,
    ("devices.Device", "offline_since"): None,
    ("devices.Device", "offline_notified_at"): None,
    ("devices.Device", "revoked_at"): None,
    ("devices.Device", "revoked_by"): None,
    # Phase 7b: imported printer delivery is inert until re-created on the target.
    ("devices.DeviceCommand", "status"): "cancelled",
    ("devices.DeviceCommand", "lease_token_digest"): None,
    ("devices.DeviceCommand", "lease_expires_at"): None,
    ("devices.PrinterDeviceBinding", "enabled"): False,
    ("devices.PrinterDeviceBinding", "auto_apply_terminal"): False,
    ("devices.PrinterJob", "state"): "needs_review",
    # Phase 7c: acknowledged delivery ownership cannot travel.
    ("devices.DeviceCommand", "acknowledged_at"): None,
    # Target operators re-enable renewal, scheduled work and optional disclosures.
    ("makerspaces.MembershipPlan", "auto_renew"): False,
    ("makerspaces.MembershipPlan", "reminder_days_before"): [],
    ("makerspaces.MembershipPlan", "reminder_days_after"): [],
    ("makerspaces.MembershipTerm", "renewal_attempts"): 0,
    ("makerspaces.MembershipTerm", "renewal_retry_at"): None,
    ("bookings.Booking", "calendar_sequence"): 0,
    ("machines.Machine", "public_fields"): [],
    ("operations.StocktakePolicy", "variance_threshold"): None,
    ("operations.StocktakeSession", "variance_threshold"): None,
    ("operations.StocktakeSession", "approval_required"): True,
    ("operations.StocktakeSchedule", "is_active"): False,
    # Source-keyed codes are replaced and revoked at the actual target import time.
    ("events.EventInvite", "code_digest"): secrets.token_hex,
    ("events.EventInvite", "email_digest"): "",
    ("events.EventInvite", "revoked_at"): timezone.now,
    ("events.EventPromoCode", "code_digest"): secrets.token_hex,
    ("events.EventPromoCode", "revoked_at"): timezone.now,
}
