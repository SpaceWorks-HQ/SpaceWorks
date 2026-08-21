import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { OrganizationReportResponse } from "../organizationAnalyticsApi";
import { OrganizationAnalyticsPanel } from "./OrganizationAnalyticsPanel";

const { staffRequest } = vi.hoisted(() => ({ staffRequest: vi.fn() }));

vi.mock("../../../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../../../lib/api")>("../../../lib/api");
  return { ...actual, staffRequest };
});

const report: OrganizationReportResponse = {
  report_key: "summary",
  strategy: "sum",
  breakdown: [
    { makerspace_id: 19, rows: [{ products: 2, active_loans: 1 }] },
    { makerspace_id: 20, rows: [{ products: 3, active_loans: 1 }] },
  ],
  total: { rows: [{ products: 5, active_loans: 2 }] },
};

const makerspaces = [
  { id: 19, name: "North workshop" },
  { id: 20, name: "South workshop" },
] as Parameters<typeof OrganizationAnalyticsPanel>[0]["makerspaces"];

function renderPanel(response: OrganizationReportResponse | Promise<never> = report) {
  staffRequest.mockReturnValue(response instanceof Promise ? response : Promise.resolve(response));
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <OrganizationAnalyticsPanel makerspaces={makerspaces} />
    </QueryClientProvider>,
  );
}

function selectOrganization(id = "7") {
  fireEvent.change(screen.getByLabelText("Organization ID"), { target: { value: id } });
}

beforeEach(() => {
  staffRequest.mockReset();
});

describe("OrganizationAnalyticsPanel", () => {
  it("renders the per-makerspace breakdown and organization total together", async () => {
    renderPanel();
    selectOrganization();

    expect(await screen.findByRole("heading", { name: "Breakdown by makerspace" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "North workshop" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "South workshop" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "Organization total" })).toBeVisible();
    expect(screen.getByRole("table", { name: "North workshop report" })).toBeVisible();
    expect(screen.getByRole("table", { name: "Organization total" })).toBeVisible();
    expect(staffRequest).toHaveBeenCalledWith("/admin/organizations/7/analytics/summary");
  });

  it("renders a table skeleton while the request is pending", () => {
    renderPanel(new Promise(() => {}));
    selectOrganization();

    expect(screen.getByLabelText("Loading organization analytics")).toBeVisible();
  });

  it("treats an empty breakdown as an empty result rather than an error", async () => {
    renderPanel({ ...report, breakdown: [], total: { rows: [] } });
    selectOrganization();

    expect(await screen.findByRole("heading", { name: "No makerspaces in this organization" }))
      .toBeVisible();
    expect(screen.queryByRole("heading", { name: "Unable to load organization analytics" }))
      .not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Organization total" })).not.toBeInTheDocument();
  });

  it("shows a retryable error state", async () => {
    renderPanel();
    staffRequest.mockRejectedValueOnce(new Error("Network unavailable"));
    selectOrganization();

    expect(await screen.findByText("Network unavailable")).toBeVisible();
    staffRequest.mockResolvedValueOnce(report);
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(staffRequest).toHaveBeenCalledTimes(2));
  });

  it("does not offer server-excluded machine-service reports", () => {
    renderPanel();
    const selector = screen.getByLabelText("Report");

    expect(within(selector).queryByRole("option", { name: "Machine service" }))
      .not.toBeInTheDocument();
    expect(within(selector).queryByRole("option", { name: "Printer service" }))
      .not.toBeInTheDocument();
    expect(Array.from((selector as HTMLSelectElement).options, (option) => option.value))
      .not.toEqual(expect.arrayContaining(["machine-service", "printer-service"]));
  });
});
