import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { ReportCatalogItem } from "./operationsReportsConfig";
import { OperationsReportExports } from "./OperationsReportExports";

const { staffRequest } = vi.hoisted(() => ({ staffRequest: vi.fn(() => Promise.resolve([])) }));
const schedulesProps = vi.hoisted(() => ({ last: [] as ReportCatalogItem[] }));

vi.mock("../../../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../../../lib/api")>("../../../lib/api");
  return { ...actual, staffRequest };
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
});
