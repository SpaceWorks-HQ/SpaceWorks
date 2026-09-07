import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { StructuredApiError } from "../../../lib/api";
import { expectNoA11yViolations } from "../../../test/axe";
import type { ReportCatalogItem } from "./operationsReportsConfig";
import { ReportSchedules } from "./ReportSchedules";
import { validateScheduleForm } from "./ReportScheduleForm";
import { parseRecipientEmails, type ReportSchedule } from "./reportSchedulesApi";

const { staffRequest } = vi.hoisted(() => ({ staffRequest: vi.fn() }));

vi.mock("../../../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../../../lib/api")>("../../../lib/api");
  return { ...actual, staffRequest };
});

const reports: ReportCatalogItem[] = [
  { key: "most-lent", title: "Most lent", fields: [], exportable: true, summary: false, required_modules: [], available: true, unavailable_reason: null, grains: ["day", "month"], chart_hint: "table", aggregate_supported: true },
  { key: "payment-reconciliation", title: "Payment reconciliation", fields: [], exportable: true, summary: false, required_modules: ["payments"], available: true, unavailable_reason: null, grains: ["day"], chart_hint: "table", aggregate_supported: true },
];

const schedule: ReportSchedule = {
  id: 3,
  makerspace: 7,
  report_key: "most-lent",
  filters: { window_days: 7 },
  grain: "day",
  format: "xlsx",
  cadence: "weekly",
  next_run_at: "2026-09-08T06:00:00Z",
  last_run_at: "2026-09-01T06:00:00Z",
  is_active: true,
  destination: 21,
  recipient_emails: ["ops@example.com"],
  created_by: 1,
  created_at: "2026-08-01T00:00:00Z",
  updated_at: "2026-08-01T00:00:00Z",
  last_delivery: null,
};

const destinations = [
  { id: 21, channel: "slack", label: "Ops room", telegram_chat_id: "", is_active: true, credential_set: true, signing_secret_set: false, scope: { machine_type_ids: [], machine_ids: [], category_ids: [] }, created_at: "", updated_at: "" },
];

function route(path: string, options?: RequestInit) {
  if (path.endsWith("/run-now")) return Promise.resolve({ id: 9, status: "sent", error: "", created_at: "2026-09-04T00:00:00Z", expires_at: null, download_url: "https://files.example/report.xlsx" });
  if (options?.method === "POST" || options?.method === "PATCH") return Promise.resolve({ ...schedule, id: 4 });
  if (options?.method === "DELETE") return Promise.resolve(undefined);
  if (path.endsWith("/notification-destinations")) return Promise.resolve(destinations);
  if (path.endsWith("/report-schedules")) return Promise.resolve([schedule]);
  return Promise.resolve([]);
}

function renderPanel() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ReportSchedules makerspaceId={7} reports={reports} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  staffRequest.mockReset();
  staffRequest.mockImplementation(route);
});

describe("ReportSchedules", () => {
  it("lists schedules with next and last run and runs one now, linking the file", async () => {
    const { container } = renderPanel();

    expect(await screen.findByText("Most lent")).toBeVisible();
    expect(screen.getByText(/Next run .* last run/)).toBeVisible();
    expect(screen.getByText(/weekly · XLSX · grain day · last 7 days · Ops room · ops@example.com/)).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: "Run now" }));

    await waitFor(() => expect(staffRequest).toHaveBeenCalledWith("/admin/report-schedules/3/run-now", { method: "POST" }));
    const link = await screen.findByRole("link", { name: "Download the file" });
    expect(link).toHaveAttribute("href", "https://files.example/report.xlsx");

    await expectNoA11yViolations(container);
  });

  it("reports a skipped run instead of a raw 409", async () => {
    staffRequest.mockImplementation((path: string, options?: RequestInit) =>
      path.endsWith("/run-now")
        ? Promise.reject(new StructuredApiError(409, { detail: "Schedule is inactive or was skipped.", code: "report_schedule_skipped" }))
        : route(path, options));
    renderPanel();
    fireEvent.click(await screen.findByRole("button", { name: "Run now" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("The schedule is inactive or was skipped, so nothing was generated.");
  });

  it("creates a schedule from the form, pauses and deletes after confirmation", async () => {
    renderPanel();
    await screen.findByText("Most lent");

    fireEvent.click(screen.getByRole("button", { name: "New schedule" }));
    const form = screen.getByRole("form", { name: "New report schedule" });
    expect(form).toBeVisible();
    fireEvent.change(screen.getByRole("combobox", { name: "Report" }), { target: { value: "payment-reconciliation" } });
    fireEvent.change(screen.getByRole("combobox", { name: "Cadence" }), { target: { value: "monthly" } });
    fireEvent.change(screen.getByRole("combobox", { name: "Chat destination" }), { target: { value: "21" } });
    fireEvent.change(screen.getByRole("textbox", { name: /Recipient emails/ }), { target: { value: "a@example.com, b@example.com" } });
    fireEvent.change(screen.getByRole("textbox", { name: /Window/ }), { target: { value: "30" } });
    fireEvent.click(screen.getByRole("button", { name: "Create schedule" }));

    await waitFor(() => expect(staffRequest).toHaveBeenCalledWith(
      "/admin/makerspaces/7/report-schedules",
      {
        method: "POST",
        body: JSON.stringify({
          report_key: "payment-reconciliation", grain: "day", format: "csv", cadence: "monthly",
          destination: 21, recipient_emails: ["a@example.com", "b@example.com"], filters: { window_days: 30 },
        }),
      },
    ));

    fireEvent.click(screen.getByRole("button", { name: "Pause" }));
    await waitFor(() => expect(staffRequest).toHaveBeenCalledWith(
      "/admin/report-schedules/3",
      { method: "PATCH", body: JSON.stringify({ is_active: false }) },
    ));

    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    expect(await screen.findByRole("dialog")).toBeVisible();
    expect(staffRequest).not.toHaveBeenCalledWith("/admin/report-schedules/3", { method: "DELETE" });
    fireEvent.click(screen.getByRole("button", { name: "Delete schedule" }));
    await waitFor(() => expect(staffRequest).toHaveBeenCalledWith("/admin/report-schedules/3", { method: "DELETE" }));
  });

  it("requires a destination or an email, like the serializer", () => {
    const base = { report_key: "most-lent", grain: "day", format: "csv" as const, cadence: "weekly" as const, destination: "", recipients: "", window_days: "" };
    expect(validateScheduleForm(base)).toMatch(/chat destination or add at least one email/);
    expect(validateScheduleForm({ ...base, destination: "21" })).toBeNull();
    expect(validateScheduleForm({ ...base, recipients: "not-an-email" })).toMatch(/not valid/);
    expect(parseRecipientEmails("a@x.io,\n b@x.io ; a@x.io")).toEqual(["a@x.io", "b@x.io"]);
  });
});
