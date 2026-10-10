import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { OperationsReports } from "./OperationsReports";
import type { Makerspace } from "./shared";

const { staffRequest } = vi.hoisted(() => ({ staffRequest: vi.fn() }));
vi.mock("../../../lib/api", async () => ({ ...await vi.importActual("../../../lib/api"), staffRequest }));

const space = { id: 7, name: "Lab", enabled_modules: ["reports"] } as Makerspace;
function panel(canViewFinance: boolean) {
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <OperationsReports makerspace={space} makerspaces={[space]} isSuperadmin={false}
      canViewAudit={false} canManageMachines={false} canViewFinance={canViewFinance} />
  </QueryClientProvider>);
}

beforeEach(() => {
  staffRequest.mockReset();
  window.localStorage.clear();
  staffRequest.mockImplementation((url: string) => Promise.resolve(url.endsWith("/catalog") ? {
    results: [{ key: "payment-reconciliation", title: "Payment reconciliation", available: true,
      exportable: true, required_modules: [], fields: [], grains: ["day"], chart_hint: "table" }],
  } : { typed_rows: [], rows: [] }));
});

describe("finance report delegation", () => {
  it("loads the money report for a finance reader without requesting hardware metrics", async () => {
    panel(true);
    await waitFor(() => expect(staffRequest).toHaveBeenCalledWith("/admin/makerspace/7/analytics/payment-reconciliation?"));
    expect(screen.getByRole("heading", { name: "Payment reconciliation" })).toBeInTheDocument();
    expect(screen.queryByText("Products")).not.toBeInTheDocument();
    expect(staffRequest.mock.calls.some(([url]) => String(url).includes("/analytics/summary"))).toBe(false);
  });

  it("does not mount the money report without view_finance", async () => {
    staffRequest.mockResolvedValue({ results: [] });
    panel(false);
    await waitFor(() => expect(staffRequest).toHaveBeenCalledWith("/admin/makerspace/7/reports/catalog"));
    expect(screen.queryByRole("heading", { name: "Payment reconciliation" })).not.toBeInTheDocument();
    expect(staffRequest.mock.calls.some(([url]) => String(url).includes("/analytics/payment-reconciliation"))).toBe(false);
  });
});
