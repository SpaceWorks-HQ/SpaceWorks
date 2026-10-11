import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ReportCatalogItem } from "./operationsReportsConfig";
import { OperationsReportExports } from "./OperationsReportExports";

const { staffRequest } = vi.hoisted(() => ({ staffRequest: vi.fn(() => Promise.resolve([])) }));
const schedulesProps = vi.hoisted(() => ({ last: [] as ReportCatalogItem[] }));
const { downloadStaffFile } = vi.hoisted(() => ({ downloadStaffFile: vi.fn(() => Promise.resolve()) }));

vi.mock("../../../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../../../lib/api")>("../../../lib/api");
  return { ...actual, staffRequest, downloadStaffFile };
});
vi.mock("./ReportSchedules", () => ({
  ReportSchedules: ({ reports }: { reports: ReportCatalogItem[] }) => {
    schedulesProps.last = reports;
    return <div>schedules</div>;
  },
}));

const base = { fields: [], exportable: true, summary: false, required_modules: [], available: true, unavailable_reason: null, grains: ["day"], chart_hint: "table", aggregate_supported: false };
const reports: ReportCatalogItem[] = [
  { ...base, key: "audit-trail", title: "Audit trail", allowed_formats: ["csv"], schedulable: false, previewable: false },
  { ...base, key: "most-lent", title: "Most lent" },
];

describe("OperationsReportExports", () => {
  beforeEach(() => { downloadStaffFile.mockClear(); staffRequest.mockClear(); });
  it("offers only allowed formats and never schedules an unschedulable report", () => {
    const client = new QueryClient();
    render(
      <QueryClientProvider client={client}>
        <OperationsReportExports reports={reports} selectedReport="most-lent" onSelect={() => undefined}
          reportsBase="/admin/makerspace/7/reports" dateSuffix="" grain="day" aggregate={false}
          makerspaceId={7} reportsEnabled />
      </QueryClientProvider>,
    );
    const audit = screen.getByText("Audit trail").parentElement as HTMLElement;
    expect(Array.from(audit.querySelectorAll("button")).map((b) => b.textContent)).toEqual(["CSV"]);
    const lent = screen.getByText("Most lent").parentElement as HTMLElement;
    expect(Array.from(lent.querySelectorAll("button")).map((b) => b.textContent)).toEqual(["CSV", "XLSX"]);
    expect(schedulesProps.last.map((report) => report.key)).toEqual(["most-lent"]);
    expect(staffRequest).not.toHaveBeenCalled();
  });

  it("uses the clicked report's grain and filters even before selection updates", async () => {
    const entries: ReportCatalogItem[] = [
      { ...base, key: "membership-revenue", title: "MRR", grains: ["month"] },
      { ...base, key: "member-retention", title: "Retention" },
      { ...base, key: "payment-reconciliation", title: "Payments" },
    ];
    render(<QueryClientProvider client={new QueryClient()}>
      <OperationsReportExports reports={entries} selectedReport="payment-reconciliation" onSelect={vi.fn()}
        reportsBase="/admin/makerspace/7/reports" dateSuffix="&start=2026-01-01" grain="day"
        filters={{ months: "6", status: "pending", subject_type: "membership_term" }}
        aggregate={false} makerspaceId={7} reportsEnabled />
    </QueryClientProvider>);
    fireEvent.click(within(screen.getByText("MRR").parentElement!).getByRole("button", { name: "CSV" }));
    await waitFor(() => expect(downloadStaffFile).toHaveBeenCalledWith(
      "/admin/makerspace/7/reports/membership-revenue/export?format=csv&start=2026-01-01&grain=month", "membership-revenue.csv"));
    const retention = within(screen.getByText("Retention").parentElement!).getByRole("button", { name: "CSV" });
    await waitFor(() => expect(retention).toBeEnabled());
    fireEvent.click(retention);
    await waitFor(() => expect(downloadStaffFile).toHaveBeenCalledWith(
      "/admin/makerspace/7/reports/member-retention/export?format=csv&start=2026-01-01&grain=day&months=6", "member-retention.csv"));
  });
});
