"""Independent literal pins for Waves 1-4, never derived from production rules."""

from apps.tenant_migration.tenant_dump_types import AuthorityDisposition as D


def _fields(label, names, disposition):
    return {(label, name): (disposition,) for name in names.split()}


RESEARCH_EXPECTED = {
    **_fields("operations.SavedView", "shared state", D.RESET),
    **_fields("makerspaces.MakerspaceMembershipSettings", "join_mode vouch_replaces_approval", D.RESET),
    **_fields("makerspaces.MembershipRequest", "admission_managed", D.RESET),
    ("makerspaces.MembershipRequest", "application_answers"): (D.PRESERVE, D.DROP),
    **_fields("makerspaces.MembershipVouch", "voucher created_at expires_at", D.PRESERVE),
    **_fields("payments.MakerspaceBillingSettings", "payment_terms_days", D.PRESERVE),
    **_fields("payments.MakerspaceBillingSettings", "reminder_days_before reminder_days_after max_reminders", D.RESET),
    **_fields("payments.Payment", "due_at", D.PRESERVE),
    **_fields("makerspaces.Makerspace", "timezone country opening_hours", D.PRESERVE),
    **_fields("machines.MakerspaceMachineTypePolicy",
              "id makerspace machine_type cert_reminder_days reminder_lead_days grace_days", D.PRESERVE),
    **_fields("maintenance.MaintenanceSchedule", "anchor", D.PRESERVE),
    **_fields("makerspaces.MakerspaceLoanPolicy",
              "makerspace default_loan_days loan_renewal_mode loan_max_renewals loan_renewal_days "
              "loan_max_active loan_max_items loan_reminder_offsets_hours loan_escalate_overdue_days", D.PRESERVE),
    **_fields("makerspaces.MembershipPlan", "loan_max_active loan_max_items", D.PRESERVE),
    **_fields("inventory.Category", "loan_days max_renewals", D.PRESERVE),
    **_fields("inventory.InventoryProduct",
              "loan_days max_renewals reorder_point reorder_quantity kit_components", D.PRESERVE),
    **_fields("boxes.Box", "kit_components", D.PRESERVE),
    **_fields("hardware_requests.HardwareRequest", "renewal_count box_issue_checklist", D.PRESERVE),
    **_fields("hardware_requests.HardwareRequestItem", "issue_checklist", D.PRESERVE),
    **_fields("hardware_requests.ReturnEvent", "kit_checklist", D.PRESERVE),
}
