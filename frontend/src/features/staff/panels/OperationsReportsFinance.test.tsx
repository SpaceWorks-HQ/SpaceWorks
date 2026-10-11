import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { OperationsReportsFinance } from "./OperationsReportsFinance";
import type { ReportCatalogItem } from "./operationsReportsConfig";

const { useStaffGet } = vi.hoisted(() => ({ useStaffGet: vi.fn() }));
vi.mock("./shared", async () => ({ ...await vi.importActual<typeof import("./shared")>("./shared"), useStaffGet }));

const report: ReportCatalogItem = {
  key: "revenue-over-time", title: "Revenue", fields: [], exportable: true, summary: false,
  required_modules: [], available: true, unavailable_reason: null, grains: ["day", "week", "month"],
  chart_hint: "line", aggregate_supported: false,
};

describe("Finance report charts", () => {
  it("keeps currencies separate while summing subjects inside each local period", () => {
    useStaffGet.mockReturnValue({ isLoading: false, error: null, data: { rows: [], typed_rows: [
      { period: "2026-10-11", currency: "usd", subject_type: "booking", collected_amount: "10.00", owed_amount: "2.00", refunded_amount: "1.00" },
      { period: "2026-10-11", currency: "usd", subject_type: "loan_deposit", collected_amount: "5.00", owed_amount: "1.00", refunded_amount: "1.00" },
      { period: "2026-10-11", currency: "inr", subject_type: "booking", collected_amount: "500.00", owed_amount: "20.00", refunded_amount: "10.00" },
    ] } });
    render(<OperationsReportsFinance catalog={[report]} analyticsBase="/admin/makerspace/7/analytics" scopeKey={7}
      startDate="" endDate="" grain="week" aggregate={false} makerspaceName={id => String(id)} />);
    expect(screen.getByLabelText("Line chart of Collected USD: 2026-10-11: 15")).toBeVisible();
    expect(screen.getByLabelText("Line chart of Collected INR: 2026-10-11: 500")).toBeVisible();
    expect(screen.getByLabelText("Line chart of Owed USD: 2026-10-11: 3")).toBeVisible();
    expect(useStaffGet.mock.calls[0][1]).toContain("grain=week");
  });
});
