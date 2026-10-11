"""Deny policy for audit call sites whose action or metadata is not a literal.

Any action matching these sets/prefixes always projects ``meta={}`` and no link, even
when another emitter writes the same string with literal metadata: at read time the row
cannot say which call site wrote it. ``presentation_discovery`` keeps this exact.
"""

# Literal actions whose metadata is built at runtime somewhere.
NON_LITERAL_META_ACTIONS = frozenset({
    "audit.signing_key_rotation_aborted",
    "audit.signing_key_rotation_completed",
    "audit.signing_key_rotation_failed",
    "audit.signing_key_rotation_started",
    "backup.settings_updated",
    "data_export.download_url_issued",
    "data_export.downloaded",
    "data_export.requested",
    "email_template.type_reset",
    "email_template.type_updated",
    "encryption.scoped_pii_decrypted",
    "event.series_organizer_deleted",
    "maintenance.logged",
    "makerspace.archived",
    "makerspace.capabilities_changed",
    "makerspace.geofence_updated",
    "makerspace.module_purge_started",
    "makerspace.module_purged",
    "makerspace.purge_started",
    "makerspace.purged",
    "membership.adopted_from_import",
    "notification.recipients_selected",
    "presence.started",
    "qr.rebound",
    "role.deleted",
})

# Every constant a resolvable dynamic action (``a if x else b``) can produce.
DYNAMIC_EXACT_ACTIONS = frozenset({
    "event.calendar_feed_created",
    "event.calendar_feed_rotated",
    "event.collaboration_accepted",
    "event.collaboration_declined",
    "event.series_collaboration_accepted",
    "event.series_collaboration_declined",
    "event.series_organizer_created",
    "event.series_organizer_updated",
    "machine_type_pricing.set",
    "machine_type_pricing.updated",
    "member.profile_image_cleared",
    "member.profile_image_updated",
    "membership.approved",
    "membership.joined",
    "membership.left",
    "membership.revoked",
    "organization.created",
    "organization.link_created",
    "organization.link_updated",
    "organization.membership_created",
    "organization.membership_updated",
    "organization.updated",
    "payment.paid_offline",
    "payment.refund_failed",
    "payment.refunded",
    "payment.waived",
    "payments.connect_deauthorization_ignored",
    "payments.connect_deauthorized",
    "payments.connect_status_update_ignored",
    "payments.connect_status_updated",
    "qr.tool_created",
    "qr.tool_reused",
    "report_schedule.delivered",
    "report_schedule.failed",
    "staff.created",
    "staff.membership_updated",
    "superadmin.break_glass_space_manager_created",
    "superadmin.break_glass_space_manager_password_reset",
    "user.password_reset",
    "warranty.created",
    "warranty.updated",
})

# Reviewed namespaces for call sites that take the action from a parameter, an
# attribute or an f-string (path relative to backend/apps -> denied prefixes).
WRAPPER_SITE_PREFIXES = {
    "accounts/audit_events.py": ("auth.",),
    "accounts/services_claim.py": ("member.claim_code_",),
    "admin_api/views_assets.py": ("inventory.asset_needs_fix_",),
    "admin_api/views_makerspace_images.py": ("makerspace.logo_", "makerspace.cover_",),
    "admin_api/views_needs_fix.py": ("inventory.needs_fix_",),
    "backup/recipient_states.py": ("backup.archive_recipient_",),
    "backup/recipients.py": ("backup.archive_recipient_",),
    "bookings/services_bookings.py": ("booking.",),
    "encryption/services.py": ("encryption.dek_",),
    "events/services.py": ("event.",),
    "hardware_requests/direct_loan_audit.py": ("admin_direct.",),
    "hardware_requests/problem_report_workflow.py": ("item.",),
    "hardware_requests/return_helpers.py": ("item.",),
    "hardware_requests/return_workflow.py": (
        "request.returned",
        "request.partially_returned",
        "request.closed_with_issue",
    ),
    "inventory/admin.py": ("inventory.needs_fix_",),
    "inventory/admin_image_uploads.py": (
        "inventory.image_",
        "makerspace.logo_",
        "makerspace.cover_",
    ),
    "machines/service_consumable_pools.py": ("machine_consumable_pool.",),
    "machines/service_metering.py": ("machine_consumable_pool.",),
    "machines/service_workflow_helpers.py": ("machine_service.",),
    "machines/services.py": ("machine.",),
    "machines/services_consumables.py": ("machine.",),
    "makerspaces/admin_images.py": ("makerspace.logo_", "makerspace.cover_",),
    "makerspaces/membership_verification.py": ("membership.can_",),
    "payments/connect.py": ("payments.connect_",),
    "tenant_migration/source_gate.py": ("tenant_migration.source_gate_",),
}

DENIED_ACTION_PREFIXES = tuple(
    sorted({prefix for group in WRAPPER_SITE_PREFIXES.values() for prefix in group})
)


def is_denied(action):
    return (
        action in NON_LITERAL_META_ACTIONS
        or action in DYNAMIC_EXACT_ACTIONS
        or str(action).startswith(DENIED_ACTION_PREFIXES)
    )
