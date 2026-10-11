import { render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { OperationsReportsCoverage } from "./OperationsReportsCoverage";
import type { ReportCatalogItem } from "./operationsReportsConfig";

const { useStaffGet } = vi.hoisted(() => ({ useStaffGet: vi.fn() }));
vi.mock("./shared", async () => ({ ...await vi.importActual<typeof import("./shared")>("./shared"), useStaffGet }));

describe("Coverage report grains", () => {
  it("uses a supported calendar grain when finance selects week", () => {
    useStaffGet.mockReturnValue({ isLoading: false, error: null, data: { rows: [], typed_rows: [] } });
    const report: ReportCatalogItem = {
      key: "evidence-compliance", title: "Evidence", fields: [], exportable: true, summary: false,
      required_modules: [], available: true, unavailable_reason: null, grains: ["day", "month"],
      chart_hint: "line", aggregate_supported: true,
    };
    render(<OperationsReportsCoverage catalog={[report]} analyticsBase="/admin/makerspace/7/analytics"
      scopeKey={7} startDate="" endDate="" grain="week" aggregate={false} makerspaceName={String} />);
    expect(useStaffGet.mock.calls[0][1]).toContain("grain=day");
    expect(useStaffGet.mock.calls[0][0]).toEqual(["operations-report", "evidence-compliance", 7, "", "", "day"]);
  });
});
