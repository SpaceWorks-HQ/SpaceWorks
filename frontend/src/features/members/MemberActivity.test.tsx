import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { MemberActivityPanel, type MemberActivity } from "./MemberActivity";

vi.mock("../../lib/api", () => ({ memberRequest: vi.fn(), staffRequest: vi.fn(), staffRequestBlob: vi.fn() }));
vi.mock("./MemberCalendarActions", () => ({ MemberCalendarActions: () => <p>Calendar controls</p> }));
vi.mock("./MemberEventFeedback", () => ({ MemberEventFeedback: () => <p>Feedback controls</p> }));

const modules = ["membership", "request_workflow", "machines", "bookings", "events", "presence"];
const activity: MemberActivity = {
  active_hardware_loans: [{ request_id: 12, can_renew: true, label: "Drill", checked_out_at: "2026-10-01", due_at: "2026-10-12", overdue: false }],
  machine_service_requests: [{ machine_type: "3d_printer", title: "Print job", status: "queued", queue_position: 2 }],
  bookings: { upcoming: [{ space_name: "Bench", starts_at: "2026-11-01", ends_at: "2026-11-02", status: "confirmed" }], past: [] },
  event_registrations: [{ registration_id: 3, event_title: "Workshop", starts_at: "2026-11-01", status: "registered", waitlist_position: null,
    can_cancel: false, cancellation_cutoff_at: "2026-10-20T12:00:00Z", checkin_token: "qr-token", feedback_available: true, feedback_path: "/feedback", certificate: null }],
  recent_presence_sessions: [], currently_checked_in: false,
  accountability: { membership_active: true, waiver_acceptance_required: true, restriction_code: null },
};
function show(section?: "overview" | "loans" | "bookings" | "events", enabled = modules, data = activity) {
  return render(<QueryClientProvider client={new QueryClient()}>
    <MemberActivityPanel section={section} modules={enabled} activity={data} makerspaceId={7} makerspaceSlug="lab" />
  </QueryClientProvider>);
}

it.each([
  ["overview", ["My activity", "3D print requests", "Recent presence"]],
  ["loans", ["Active hardware loans"]],
  ["bookings", ["Bookings"]],
  ["events", ["Event registrations"]],
] as const)("renders only the %s sections", (section, titles) => {
  show(section);
  expect(screen.getAllByRole("heading", { level: 2 }).map((heading) => heading.textContent)).toEqual(titles);
});

it("keeps the full activity view when no section is selected", () => {
  show();
  expect(screen.getAllByRole("heading", { level: 2 })).toHaveLength(6);
  expect(screen.getByRole("button", { name: "Renew loan" })).toBeVisible();
});

it("hides stale domain data and actions when modules are disabled", () => {
  show(undefined, ["membership"]);
  expect(screen.getAllByRole("heading", { level: 2 }).map((heading) => heading.textContent)).toEqual(["My activity"]);
  expect(screen.queryByRole("button", { name: "Renew loan" })).toBeNull();
  expect(screen.queryByText("Calendar controls")).toBeNull();
  expect(screen.queryByRole("button", { name: "Show check-in QR" })).toBeNull();
});

it("honours the server's cancellation refusal while retaining QR, feedback and calendar controls", () => {
  show("events");
  expect(screen.getByText("The cancellation deadline has passed. Contact staff.")).toBeVisible();
  expect(screen.queryByRole("button", { name: "Cancel registration" })).toBeNull();
  expect(screen.getByRole("button", { name: "Show check-in QR" })).toBeVisible();
  expect(screen.getByText("Feedback controls")).toBeVisible();
  expect(screen.getByText("Calendar controls")).toBeVisible();
});

it("shows the server's cancellation cutoff when cancellation is allowed", () => {
  const cutoff = activity.event_registrations![0].cancellation_cutoff_at!;
  show("events", modules, { ...activity, event_registrations: [{ ...activity.event_registrations![0], can_cancel: true }] });
  expect(screen.getByText(`Cancel before ${new Date(cutoff).toLocaleString()}.`)).toBeVisible();
  expect(screen.getByRole("button", { name: "Cancel registration" })).toBeVisible();
});
