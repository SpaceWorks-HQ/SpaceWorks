import { describe, expect, it } from "vitest";
import { dashboardHref } from "./dashboardLinks";
describe("dashboard drill-down URL state", () => {
  it.each([
    ["pending_requests", "requests?queue=pending"], ["awaiting_issue", "requests?queue=accepted"],
    ["overdue_loans", "accountability?section=overdue"], ["open_problem_reports", "accountability?section=problems"],
    ["low_stock", "inventory?out_of_stock=true&archived=all"], ["pending_payments", "payments?status=pending"],
    ["stocktakes_awaiting_approval", "stocktake?status=completed"], ["failed_emails", "email-log?status=failed&recent_days=7"],
    ["pending_prints", "machines?work_queue=pending_prints"], ["active_prints", "machines?work_queue=active_prints"],
    ["prints_awaiting_collection", "machines?work_queue=prints_awaiting_collection"], ["maintenance_overdue", "machines?work_queue=maintenance_overdue"],
  ])("links %s to its filtered destination", (key, suffix) => {
    expect(dashboardHref(key, "forge")).toBe(`/m/forge/admin/${suffix}`);
    expect(dashboardHref(key, "forge", true)).toBe(`/admin/${suffix}`);
  });
  it("sets an inclusive thirty-day warranty cutoff", () => {
    expect(dashboardHref("warranty_expiring", "forge", false, false, new Date(2026, 9, 11))).toBe("/m/forge/admin/warranty?expires_before=2026-11-10");
  });
});
