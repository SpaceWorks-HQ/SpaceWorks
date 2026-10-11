import { staffTabPath } from "../staffTabs";
const destinations: Record<string, { tab: string; filters: Record<string, string> }> = {
  upcoming_events: { tab: "events", filters: { status: "published" } },
  pending_event_registrations: { tab: "events", filters: {} },
  pending_bookings: { tab: "bookings", filters: { status: "pending" } },
  upcoming_bookings: { tab: "bookings", filters: { status: "confirmed" } },
  overdue_loans: { tab: "accountability", filters: { section: "overdue" } },
  pending_requests: { tab: "requests", filters: { queue: "pending" } },
  awaiting_issue: { tab: "requests", filters: { queue: "accepted" } },
  open_problem_reports: { tab: "accountability", filters: { section: "problems" } },
  low_stock: { tab: "inventory", filters: { out_of_stock: "true", archived: "all" } },
  pending_prints: { tab: "machines", filters: { work_queue: "pending_prints" } },
  active_prints: { tab: "machines", filters: { work_queue: "active_prints" } },
  prints_awaiting_collection: { tab: "machines", filters: { work_queue: "prints_awaiting_collection" } },
  failed_emails: { tab: "email-logs", filters: { status: "failed", recent_days: "7" } },
  stocktakes_awaiting_approval: { tab: "stocktake", filters: { status: "completed" } },
  warranty_expiring: { tab: "warranty", filters: {} },
  maintenance_overdue: { tab: "machines", filters: { work_queue: "maintenance_overdue" } },
  pending_payments: { tab: "payments", filters: { status: "pending" } },
};

export function dashboardDestination(key: string) { return destinations[key]; }
export function dashboardHref(key: string, slug: string, single = false, guest = false, today = new Date()) {
  const destination = destinations[key];
  if (!destination) return "";
  const filters = { ...destination.filters };
  if (key === "warranty_expiring") { const date = new Date(today); date.setDate(date.getDate() + 30); filters.expires_before = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`; }
  return `${staffTabPath(destination.tab, guest, slug, single)}?${new URLSearchParams(filters)}`;
}
