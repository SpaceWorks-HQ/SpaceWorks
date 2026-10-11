import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import { emptyScheduleForm, formToInput, ReportScheduleForm, scheduleToForm, validateScheduleForm } from "./ReportScheduleForm";
import type { ReportCatalogItem } from "./operationsReportsConfig";
import type { ReportSchedule } from "./reportSchedulesApi";

const reports: ReportCatalogItem[] = [{ key: "membership-revenue", title: "MRR", fields: ["mrr", "currency"],
  grains: ["month"], required_modules: ["membership"], exportable: true, summary: false, available: true,
  unavailable_reason: null, chart_hint: "table", aggregate_supported: false, condition_metrics: ["mrr"] }];

it("allows dynamic recipients without a frozen address and carries a numeric condition", () => {
  const form = { ...emptyScheduleForm(reports), role_slugs: "treasurer", actions: "view_finance", non_empty: true,
    metric: "mrr", threshold: "100.50", comparison: "gte", currency: "usd" };
  expect(validateScheduleForm(form)).toBeNull();
  const input = formToInput(form);
  expect(input.recipient_emails).toEqual([]);
  expect(input.recipient_roles).toEqual(["treasurer"]);
  expect(input.recipient_actions).toEqual(["view_finance"]);
  expect(input.condition).toEqual({ non_empty: true, metric: "mrr", operator: "gte", value: "100.50", currency: "usd" });
  const schedule: ReportSchedule = { ...input, id: 1, makerspace: 7, created_by: 1,
    next_run_at: "2026-01-01T00:00:00Z", last_run_at: null, is_active: true,
    created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z", last_delivery: null };
  const roundTrip = scheduleToForm(schedule);
  expect(roundTrip.role_slugs).toBe("treasurer");
  expect(roundTrip.threshold).toBe("100.50");
});

it("offers curated metrics and submits the non-empty rule", () => {
  const submit = vi.fn();
  render(<ReportScheduleForm reports={reports} destinations={[]} initial={emptyScheduleForm(reports)} editing={false} pending={false} onSubmit={submit} />);
  expect(screen.queryByRole("option", { name: "currency" })).not.toBeInTheDocument();
  fireEvent.change(screen.getByRole("textbox", { name: /Recipient role slugs/ }), { target: { value: "treasurer" } });
  fireEvent.click(screen.getByRole("checkbox", { name: "Send only when non-empty" }));
  fireEvent.click(screen.getByRole("button", { name: "Create schedule" }));
  expect(submit).toHaveBeenCalledWith(expect.objectContaining({ recipient_roles: ["treasurer"], condition: { non_empty: true } }));
});

it("preserves pinned filters while editing conditions and replaces dates with a moving window", () => {
  const form = { ...emptyScheduleForm(reports), window_days: "", role_slugs: "treasurer",
    pinned_filters: { start: "2026-01-01", end: "2026-01-31", status: "pending" } };
  expect(formToInput(form).filters).toEqual(form.pinned_filters);
  expect(formToInput({ ...form, window_days: "30" }).filters).toEqual({ window_days: 30, status: "pending" });
});

it("clears report-specific pinned filters when choosing a different report", () => {
  const submit = vi.fn();
  render(<ReportScheduleForm reports={[...reports, { ...reports[0], key: "member-retention", title: "Retention", grains: ["day"] }]}
    destinations={[]} initial={{ ...emptyScheduleForm(reports), window_days: "", role_slugs: "treasurer",
      pinned_filters: { start: "2026-01-01", status: "pending" } }} editing pending={false} onSubmit={submit} />);
  fireEvent.change(screen.getByRole("combobox", { name: "Report" }), { target: { value: "member-retention" } });
  fireEvent.click(screen.getByRole("button", { name: "Save schedule" }));
  expect(submit).toHaveBeenCalledWith(expect.objectContaining({ report_key: "member-retention", filters: { start: "2026-01-01" } }));
});
