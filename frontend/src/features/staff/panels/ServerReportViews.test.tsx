import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

import { ServerReportViews } from "./ServerReportViews";
import type { ReportViewState } from "./reportViewsApi";

const { request } = vi.hoisted(() => ({ request: vi.fn() }));
vi.mock("../../../lib/api", () => ({ staffRequest: request }));
const state: ReportViewState = { report_key: "membership-revenue", grain: "month", filters: { start: "2026-01-01" }, columns: ["mrr"] };
const row = { id: 3, makerspace: 7, owner: 1, name: "Board report", state, shared: true };
const onApply = vi.fn();

beforeEach(() => {
  request.mockReset(); onApply.mockReset();
  request.mockImplementation((path: string, options?: RequestInit) => Promise.resolve(
    options?.method === "DELETE" ? undefined : options?.method === "POST" || path.endsWith("/3") ? row : { count: 1, next: null, previous: null, results: [row] },
  ));
});

function panel() {
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })}>
    <ServerReportViews makerspaceId={7} state={state} fields={["mrr", "arr"]} onColumns={vi.fn()} onApply={onApply} />
  </QueryClientProvider>);
}

it("saves report filters and columns on the server and refreshes the list", async () => {
  panel();
  await screen.findByText("Board report (shared)");
  fireEvent.change(screen.getByRole("textbox", { name: "View name" }), { target: { value: "Finance" } });
  fireEvent.click(screen.getByRole("checkbox", { name: "Share with makerspace (managers)" }));
  fireEvent.click(screen.getByRole("button", { name: "Save view" }));
  await waitFor(() => expect(request).toHaveBeenCalledWith("/admin/makerspaces/7/saved-report-views", {
    method: "POST", body: JSON.stringify({ name: "Finance", state, shared: true }),
  }));
  await waitFor(() => expect(request.mock.calls.filter(([path]) => path.endsWith("?page=1")).length).toBeGreaterThan(1));
});

it("reauthorizes a shared view on open and displays a revoked-owner error", async () => {
  panel();
  const button = await screen.findByText("Board report (shared)");
  fireEvent.click(button);
  await waitFor(() => expect(onApply).toHaveBeenCalledWith(state));
  expect(request).toHaveBeenCalledWith("/admin/makerspaces/7/saved-report-views/3");
  request.mockRejectedValueOnce(new Error("The view owner can no longer open this report."));
  fireEvent.click(button);
  expect(await screen.findByRole("alert")).toHaveTextContent("owner can no longer open");
  expect(onApply).toHaveBeenCalledTimes(1);
});

it("deletes a saved report and refreshes server state", async () => {
  panel();
  fireEvent.click(await screen.findByRole("button", { name: "Delete Board report" }));
  await waitFor(() => expect(request).toHaveBeenCalledWith("/admin/makerspaces/7/saved-report-views/3", { method: "DELETE" }));
});
