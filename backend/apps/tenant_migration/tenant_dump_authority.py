"""Deny-by-default authority/disclosure overrides for the Lane D catalog."""

from .tenant_dump_types import AuthorityDisposition as D
from .tenant_dump_types import authority
from .tenant_dump_authority_supplement import SUPPLEMENTAL_AUTHORITY_ENTRIES

def _same(label, names, disposition, reason):
    return tuple(
        ((label, name), authority(disposition, reason)) for name in names.split()
    )

def _build(entries):
    result = {}
    for edge, rule in entries:
        if edge in result:
            raise RuntimeError(f"duplicate Lane D authority rule: {edge}")
        result[edge] = rule
    return result

_ENTRIES = (
    *_same(
        "accounts.User",
        "is_superuser is_staff role",
        D.RESET,
        "Source-global privilege cannot become target authority.",
    ),
    *_same(
        "accounts.User",
        "groups user_permissions",
        D.DROP,
        "Source-global group and direct-permission grants never travel.",
    ),
    *_same(
        "accounts.User",
        "telegram_user_id external_checkin_user_id",
        D.RESET,
        "Source-bound external login identities require target relinking.",
    ),
    *_same(
        "accounts.User",
        "id username password email phone phone_e164 phone_verified_at email_verified_at "
        "is_active access_status must_change_password is_walk_in",
        (D.PRESERVE, D.RESET),
        "Preserve the tenant-exclusive authentication tuple; reset the inert stub tuple.",
    ),
    *_same(
        "makerspaces.MakerspaceMembership",
        "status verified_at activated_at revoked_at revocation_reason waiver_accepted_at "
        "waiver_version_accepted accepted_waiver witnessed_waiver witnessed_waiver_version "
        "witnessed_at",
        D.PRESERVE,
        "Membership lifecycle and waiver evidence remain honest history.",
    ),
    *_same(
        "makerspaces.MakerspaceMembership",
        "role assigned_role can_refer can_verify receives_notifications",
        D.RESET,
        "Membership authority and delivery preferences restart at target defaults.",
    ),
    *_same(
        "makerspaces.MembershipRequest",
        "state",
        (D.PRESERVE, D.DROP),
        "Closed history travels; requested and invited rows are dropped.",
    ),
    *_same(
        "makerspaces.MembershipRequest",
        "assigned_role auto_activate_on_claim",
        D.RESET,
        "No imported request may mint target membership authority.",
    ),
    *_same(
        "makerspaces.Makerspace",
        "membership_policy referrals_enabled superadmin_access_enabled frontend_domain "
        "frontend_domain_status domain_verification_token domain_verified_at "
        "frontend_domain_changed_at cors_allowed_origins enabled_modules enabled_features "
        "resource_limit_overrides hidden_from_central_directory storage_bytes_used "
        "archived_at archived_by lifecycle_state",
        D.RESET,
        "Admission, routing, capabilities, lifecycle and accounting are target policy.",
    ),
    *_same(
        "makerspaces.Makerspace",
        "public_inventory_enabled public_stats_enabled public_stats_show_holder_names "
        "public_print_status_lookup_policy",
        D.PRESERVE,
        "These are explicit tenant publication choices, still bounded by target modules.",
    ),
    *_same(
        "makerspaces.Makerspace",
        "staff_notifications_enabled booking_requester_notifications_enabled",
        D.RESET,
        "Source delivery policy cannot begin target delivery.",
    ),
    *_same(
        "makerspaces.Makerspace",
        "public_api_key",
        D.RESET,
        "Public/status bearer tokens are regenerated for the target.",
    ),
    *_same(
        "makerspaces.Makerspace",
        "smtp_host smtp_port smtp_username smtp_password smtp_use_tls smtp_use_ssl "
        "smtp_from_email telegram_group_chat_id telegram_bot_token slack_webhook_url "
        "mattermost_webhook_url discord_webhook_url",
        D.RESET,
        "Source integration routes, credentials and rooms cannot receive target data.",
    ),
    *_same(
        "inventory.InventoryProduct",
        "is_public show_public_count public_availability_mode is_archived",
        D.PRESERVE,
        "Tenant inventory visibility and lifecycle choices travel.",
    ),
    *_same(
        "inventory.InventoryProduct",
        "public_self_checkout_enabled",
        D.RESET,
        "Public quantity checkout is a target issue grant.",
    ),
    *_same(
        "inventory.InventoryAsset",
        "public_self_checkout_enabled",
        D.RESET,
        "Per-asset public checkout is a distinct target issue grant.",
    ),
    *_same(
        "machines.Machine",
        "is_public is_active",
        D.PRESERVE,
        "Tenant machine visibility and lifecycle choices travel.",
    ),
    *_same(
        "machines.Machine",
        "camera_feed_url",
        D.RESET,
        "Source camera routes may contain credentials and cannot disclose target data.",
    ),
    *_same(
        "machines.MachineType",
        "managing_action",
        D.RESET,
        "Server-controlled custom authorization action names do not travel.",
    ),
    *_same(
        "machines.MachineOperator",
        "id machine user access_level assigned_by assigned_at",
        D.PRESERVE,
        "Owner decision 22: the exact live grant and assignment provenance travel.",
    ),
    *_same(
        "bookings.BookableSpace",
        "is_public show_public_availability show_public_booker_names is_active",
        D.PRESERVE,
        "Tenant booking visibility and lifecycle choices travel.",
    ),
    *_same(
        "bookings.BookableSpace",
        "approval_mode requester_notifications_enabled public_token",
        D.RESET,
        "Auto-approval, requester delivery and source bearer tokens reset closed.",
    ),
    *_same(
        "events.Event",
        "is_public status",
        D.PRESERVE,
        "The event publication controls are tenant-owned content.",
    ),
    *_same(
        "events.Event",
        "public_token",
        D.RESET,
        "Source event bearer tokens are regenerated.",
    ),
    *_same(
        "events.EventRegistration",
        "checkin_token registered_via_makerspace payment_via_makerspace",
        D.RESET,
        "Source check-in and cross-tenant delivery/routing bindings do not travel live.",
    ),
    *_same(
        "makerspaces.MemberProfile",
        "is_visible show_attended_events",
        (D.PRESERVE, D.DROP),
        "Full-user consent travels; every stub-linked profile is dropped.",
    ),
    *_same(
        "makerspaces.MemberProfile",
        "headline institution bio avatar_key interests languages education github_username "
        "github_contributions github_synced_at",
        (D.PRESERVE, D.DROP),
        "Full-user profile content travels; stub-linked identity content does not.",
    ),
    *_same(
        "makerspaces.MemberProject",
        "id profile title description image_key links position created_at updated_at",
        (D.PRESERVE, D.DROP),
        "Full-user projects travel; every stub-linked project and object is dropped.",
    ),
    *_same(
        "integrations.NotificationDestination",
        "channel telegram_chat_id",
        (D.PRESERVE, D.DROP),
        "Telegram identity may travel inert; webhook destinations are dropped.",
    ),
    *_same(
        "integrations.NotificationDestination",
        "is_active",
        D.RESET,
        "A carried Telegram room stays inactive until target approval.",
    ),
    *_same(
        "integrations.NotificationDestination",
        "webhook_url",
        D.DROP,
        "No source webhook credential or room may receive target data.",
    ),
    *_same(
        "integrations.DestinationCategoryScope",
        "id destination category",
        (D.PRESERVE, D.DROP),
        "Scopes travel only below a carried inert Telegram destination.",
    ),
    *_same(
        "integrations.DestinationMachineScope",
        "id destination machine",
        (D.PRESERVE, D.DROP),
        "Scopes travel only below a carried inert Telegram destination.",
    ),
    *_same(
        "integrations.DestinationMachineTypeScope",
        "id destination machine_type",
        (D.PRESERVE, D.DROP),
        "Scopes travel only below a carried inert Telegram destination.",
    ),
    *_same(
        "integrations.EmailTemplate",
        "subject text_body html_body is_active",
        D.PRESERVE,
        "Tenant-authored wording remains bounded by reset target delivery policy.",
    ),
    *_same(
        "integrations.MachineTypeEmailTemplate",
        "subject text_body html_body is_active",
        D.PRESERVE,
        "Tenant-authored wording remains bounded by reset target delivery policy.",
    ),
    *_same(
        "integrations.ChatTemplate",
        "text_body is_active",
        D.PRESERVE,
        "Tenant-authored wording remains bounded by reset target delivery policy.",
    ),
    *_same(
        "backup.MakerspaceArchiveRecipient",
        "public_recipient fingerprint label",
        D.PRESERVE,
        "Public recipient metadata travels for fresh target proof.",
    ),
    *_same(
        "backup.MakerspaceArchiveRecipient",
        "verified_at challenge_nonce_digest challenge_issued_at",
        D.RESET,
        "Source proof state is not target proof of recipient possession.",
    ),
    *_same(
        "apiclients.ApiKeyRequest",
        "status",
        (D.PRESERVE, D.DROP),
        "Approved/rejected history may travel; pending minting authority is dropped.",
    ),
    *SUPPLEMENTAL_AUTHORITY_ENTRIES,
    *_same(
        "audit.AuditLog",
        "event_uuid row_mac",
        D.RESET,
        "Rewritten rows cannot retain source signing or row-MAC claims.",
    ),
)

AUTHORITY_FIELD_OVERRIDES = _build(_ENTRIES)
NON_MODEL_AUTHORITY_INPUTS = {
    "target_native_app_registrations": authority(D.RESET, "Use exact target configuration."),
    "target_api_client_approvals": authority(D.RESET, "Fresh artifact-bound host approval only."),
    "target_module_registry": authority(D.RESET, "Target code capability is authoritative."),
    "target_domain_and_origin_configuration": authority(D.RESET, "Target routing is authoritative."),
}
