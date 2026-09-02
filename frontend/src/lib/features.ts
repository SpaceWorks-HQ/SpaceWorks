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
  { key: "payments.machines", parent_module: "machines", label: "Machine payments" },
  { key: "payments.bookings", parent_module: "bookings", label: "Booking payments" },
  { key: "payments.events", parent_module: "events", label: "Event payments" },
  { key: "payments.membership", parent_module: "membership", label: "Membership payments" },
  { key: "inventory.self_checkout", parent_module: null, label: "Self checkout" },
  { key: "payments.enabled", parent_module: "payments", label: "Payments" },
  { key: "mobile.push", parent_module: "mobile", label: "Native push" },
  { key: "presence.geofence", parent_module: null, label: "Presence geofence" },
  { key: "notifications.delegated_recipients", parent_module: "notifications", label: "Delegated maintenance recipients" },
  { key: "events.offline_checkin", parent_module: "events", label: "Offline & station check-in" },
];

export function featureEnabled(features: Iterable<string>, key: string) {
  return new Set(features).has(key);
}
