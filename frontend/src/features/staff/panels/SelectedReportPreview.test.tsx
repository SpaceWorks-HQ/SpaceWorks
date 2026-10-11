import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import { SelectedReportPreview } from "./SelectedReportPreview";
import type { ReportCatalogItem } from "./operationsReportsConfig";

const { request } = vi.hoisted(() => ({ request: vi.fn() }));
vi.mock("../../../lib/api", () => ({ staffRequest: request }));

it("uses the monthly report grain and displays only saved columns", async () => {
  request.mockResolvedValue({ rows: [["currency", "mrr", "arr"], ["usd", "20.00", "240.00"]],
    meta: { definition: "Monthly recurring plan projection" } });
  const report = { key: "membership-revenue", title: "MRR", grains: ["month"], available: true } as ReportCatalogItem;
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <SelectedReportPreview report={report} analyticsBase="/admin/makerspace/7/analytics" scopeKey={7}
      start="2026-01-01" end="" grain="day" columns={["currency", "mrr"]} months="" />
  </QueryClientProvider>);
  expect(await screen.findByRole("columnheader", { name: "mrr" })).toBeVisible();
  expect(screen.queryByRole("columnheader", { name: "arr" })).not.toBeInTheDocument();
  expect(request).toHaveBeenCalledWith("/admin/makerspace/7/analytics/membership-revenue?grain=month&start=2026-01-01");
  expect(screen.getByText("Monthly recurring plan projection")).toBeVisible();
});
