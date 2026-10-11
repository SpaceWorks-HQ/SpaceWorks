"""Independent authority pins for merged module, delivery and inventory features.

Tenant presentation and operational history travel. Source subscriptions, tokens,
scheduled work and approval exemptions cannot become live target authority.
"""

from apps.tenant_migration.tenant_dump_types import AuthorityDisposition as D


def _fields(label, names, disposition):
    return {(label, name): (disposition,) for name in names.split()}


W7_EXPECTED = {
    **_fields("makerspaces.Makerspace", "public_site_enabled public_landing_page", D.PRESERVE),
    **_fields("bookings.BookingCalendarFeed", "user token_digest token_hint revoked_at", D.DROP),
    **_fields("integrations.NotificationTimingPolicy",
              "quiet_start quiet_end channels digest_at bounce_secret", D.DROP),
    **_fields("notifications.MemberNotificationPreference", "daily_digest", D.DROP),
    **_fields("bookings.Booking", "calendar_sequence", D.RESET),
    **_fields("inventory.InventoryProduct", "borrowing_terms", D.PRESERVE),
    **_fields("inventory.InventoryWatch", "makerspace product user ready_at notified_at", D.DROP),
    **_fields("maintenance.MaintenanceCalendarFeed",
              "makerspace user token_digest token_hint revoked_at", D.DROP),
    **_fields("machines.Machine", "status_since", D.PRESERVE),
    **_fields("machines.Machine", "public_fields", D.RESET),
    **_fields("machines.MachineType", "intake_schema", D.PRESERVE),
    **_fields("machines.MachineMaterial", "makerspace machine_type name colours is_active", D.PRESERVE),
    **_fields("operations.StocktakePolicy", "makerspace blind_default", D.PRESERVE),
    **_fields("operations.StocktakePolicy", "variance_threshold", D.RESET),
    **_fields("operations.StocktakeSchedule",
              "makerspace container name interval_days next_due blind", D.PRESERVE),
    **_fields("operations.StocktakeSchedule", "is_active", D.RESET),
    **_fields("operations.StocktakeSession", "blind", D.PRESERVE),
    **_fields("operations.StocktakeSession", "variance_threshold approval_required", D.RESET),
    **_fields("maintenance.MaintenanceSchedule", "trigger usage_hours job_count meter_started_at", D.PRESERVE),
}
