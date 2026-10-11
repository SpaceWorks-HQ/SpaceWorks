export type FeatureDefinition = {
  key: string;
  // null => standalone feature with no parent-module prerequisite (always toggleable).
  parent_module: string | null;
  label: string;
};

// Mirrors `apps/makerspaces/capabilities.py::FEATURE_DEFINITIONS`. The backend test
// `tests/test_capabilities.py::test_frontend_feature_definitions_match_the_backend`
// parses this file and fails if the two drift, so keep the shape (one object literal
// per line, keys in this order) that the guard reads.
export const FEATURE_DEFINITIONS: readonly FeatureDefinition[] = [
  { key: "packs.import", parent_module: "staff_admin", label: "Space packs" },
  { key: "membership.auto_renew", parent_module: "membership", label: "Automatic membership renewal" },
  { key: "membership.lifecycle_mail", parent_module: "membership", label: "Membership lifecycle mail" },
  { key: "membership.self_service", parent_module: "membership", label: "Member account self-service" },
  { key: "membership.self_export", parent_module: "membership", label: "Member data export" },
  { key: "reports.saved_views", parent_module: "reports", label: "Saved report views" },
  { key: "billing.documents", parent_module: null, label: "Receipt documents" },
  { key: "billing.reminders", parent_module: "notifications", label: "Payment reminders" },
  { key: "loans.renewals", parent_module: "request_workflow", label: "Loan renewals" },
  { key: "loans.limits", parent_module: "request_workflow", label: "Borrow limits" },
  { key: "loans.kit_checklist", parent_module: "containers", label: "Kit checklists" },
  { key: "staff.invitations", parent_module: null, label: "Staff invitations" },
  { key: "security.staff_mfa_required", parent_module: null, label: "Require MFA for staff" },
  { key: "membership.vouching", parent_module: "membership", label: "Membership vouching" },
  { key: "membership.application_form", parent_module: "membership", label: "Membership application form" },
  { key: "payments.machines", parent_module: "machines", label: "Machine payments" },
  { key: "payments.bookings", parent_module: "bookings", label: "Booking payments" },
  { key: "payments.events", parent_module: "events", label: "Event payments" },
  { key: "payments.membership", parent_module: "membership", label: "Membership payments" },
  { key: "payments.loans", parent_module: "payments", label: "Loan deposits and late fees" },
  { key: "charges.enabled", parent_module: null, label: "Track money owed" },
  { key: "charges.bookings", parent_module: "bookings", label: "Track booking charges" },
  { key: "charges.events", parent_module: "events", label: "Track event charges" },
  { key: "charges.machines", parent_module: "machines", label: "Track machine job charges" },
  { key: "charges.membership", parent_module: "membership", label: "Track membership charges" },
  { key: "charges.loans", parent_module: "request_workflow", label: "Track loan charges" },
  { key: "inventory.self_checkout", parent_module: null, label: "Self checkout" },
  { key: "payments.enabled", parent_module: "payments", label: "Payments" },
  { key: "mobile.push", parent_module: "mobile", label: "Native push" },
  { key: "presence.geofence", parent_module: null, label: "Presence geofence" },
  { key: "notifications.delegated_recipients", parent_module: "notifications", label: "Delegated maintenance recipients" },
  { key: "notifications.member_inbox", parent_module: "notifications", label: "Member inbox" },
  { key: "notifications.member_preferences", parent_module: "notifications", label: "Member communication preferences" },
  { key: "events.invites", parent_module: "events", label: "Event invitations" },
  { key: "events.account_registration", parent_module: "events", label: "Account event registration" },
  { key: "events.ticket_types", parent_module: "events", label: "Event ticket types" },
  { key: "events.promo_codes", parent_module: "events", label: "Event promo codes" },
  { key: "events.offline_checkin", parent_module: "events", label: "Offline & station check-in" },
  { key: "machines.certification_reminders", parent_module: "machines", label: "Certification reminders" },
  { key: "maintenance.reminders", parent_module: "maintenance", label: "Maintenance reminders" },
  { key: "machines.certifications", parent_module: "machines", label: "Certification gating" },
  { key: "inventory.kiosk", parent_module: null, label: "Kiosk" },
];

export function featureEnabled(features: Iterable<string>, key: string) {
  return new Set(features).has(key);
}
