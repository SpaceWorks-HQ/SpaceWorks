"""Independent literal pins for the merged scheduling, admission and inbox lanes.

These expectations describe the shipped portability decisions, without importing
the production catalog or deriving its fields. Target delivery/admission authority
resets; tenant timing and closed accountability history travel.
"""

from apps.tenant_migration.tenant_dump_types import AuthorityDisposition as D


def _fields(label, names, dispositions):
    if not isinstance(dispositions, tuple):
        dispositions = (dispositions,)
    return [((label, name), dispositions) for name in names.split()]


INTEGRATION_EXPECTED = dict([
    *_fields("bookings.BookableSpace",
             "buffer_before_minutes buffer_after_minutes cancellation_cutoff_hours", D.PRESERVE),
    *_fields("events.Event", "cancellation_cutoff_hours", D.PRESERVE),
    *_fields("events.EventSeries", "cancellation_cutoff_hours", D.PRESERVE),
    *_fields("makerspaces.Makerspace",
             "event_reminder_lead_hours booking_reminder_lead_hours timezone country opening_hours", D.PRESERVE),
    *_fields("notifications.MemberNotificationPreference", "makerspace user feature channel enabled", D.DROP),
    *_fields("notifications.NotificationInboxRow",
             "makerspace user feature event event_key title summary link read_at", D.DROP),
    *_fields("integrations.EmailSuppression", "makerspace address_hash reason created_by", D.DROP),
    *_fields("integrations.EmailLog", "recipient feature retry_generation", D.DROP),
    *_fields("integrations.NotificationDeliveryLog", "retry_generation", D.DROP),
    *_fields("integrations.NotificationDestination", "payload_version", D.PRESERVE),
    *_fields("operations.SavedView", "shared state", D.RESET),
    *_fields("makerspaces.MakerspaceMembershipSettings", "join_mode vouch_replaces_approval", D.RESET),
    *_fields("makerspaces.MembershipRequest", "admission_managed", D.RESET),
    *_fields("makerspaces.MembershipRequest", "application_answers", (D.PRESERVE, D.DROP)),
    *_fields("makerspaces.MembershipVouch", "voucher created_at expires_at", D.PRESERVE),
    *_fields("payments.MakerspaceBillingSettings", "payment_terms_days", D.PRESERVE),
    *_fields("payments.MakerspaceBillingSettings", "reminder_days_before reminder_days_after max_reminders", D.RESET),
    *_fields("payments.Payment", "due_at", D.PRESERVE),
    *_fields("makerspaces.MakerspaceLoanPolicy",
             "makerspace default_loan_days loan_renewal_mode loan_max_renewals loan_renewal_days "
             "loan_max_active loan_max_items loan_reminder_offsets_hours loan_escalate_overdue_days", D.PRESERVE),
    *_fields("makerspaces.MembershipPlan", "loan_max_active loan_max_items", D.PRESERVE),
    *_fields("inventory.Category", "loan_days max_renewals", D.PRESERVE),
    *_fields("inventory.InventoryProduct", "loan_days max_renewals", D.PRESERVE),
    *_fields("hardware_requests.HardwareRequest", "renewal_count", D.PRESERVE),
    *_fields("machines.MakerspaceMachineTypePolicy",
             "id makerspace machine_type cert_reminder_days reminder_lead_days grace_days", D.PRESERVE),
    *_fields("maintenance.MaintenanceSchedule", "anchor", D.PRESERVE),
])
