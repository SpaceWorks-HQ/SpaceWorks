import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { EventRegistrationRoster } from "./EventRegistrationRoster";
import type { StaffEvent } from "./eventsApiTypes";

const mocks = vi.hoisted(() => ({ cancel: vi.fn(), pending: false, error: null as Error | null }));
vi.mock("./eventsApi", () => {
  const idle = () => ({ mutate: vi.fn(), isPending: false, error: null });
  return {
    useEventRegistrations: () => ({ data: { count: 6, previous: null, next: null, results:
      ["pending_approval", "registered", "waitlisted", "attended", "rejected", "cancelled"].map((status, id) => ({
        id, name: status, status, email: "", phone: "", payment: null,
      })),
    } }),
    useApproveEventRegistration: idle, useRejectEventRegistration: idle,
    usePromoteEventRegistration: idle, useMarkEventAttended: idle,
    useCancelEventRegistration: () => ({ mutate: mocks.cancel, isPending: mocks.pending, variables: 1, error: mocks.error }),
  };
});
vi.mock("./eventFeedbackApi", () => ({ useCorrectAttendance: () => ({ isPending: false, error: null }) }));
vi.mock("./EventCheckInOperator", () => ({ EventCheckInOperator: () => null }));
vi.mock("./EventBadgeActions", () => ({ EventBadgeActions: () => null }));
vi.mock("./EventRegisterMember", () => ({ EventRegisterMember: () => null }));
vi.mock("./PaymentReconcileActions", () => ({ PaymentReconcileActions: () => null }));

const event = { id: 3, status: "published", registration_counts: {}, registration_requires_approval: false } as StaffEvent;
function show() {
  render(<EventRegistrationRoster event={event} makerspaceId={7} offlineCheckInEnabled={false} />);
}
function row(status: string) {
  return screen.getAllByRole("row").find((item) => within(item).queryByText(status, { selector: "td" }))!;
}
beforeEach(() => { mocks.cancel.mockReset(); mocks.pending = false; mocks.error = null; });

describe("staff roster cancellation", () => {
  it("offers cancellation for all live registration states and posts the selected id", () => {
    show();
    expect(screen.getAllByRole("button", { name: "Cancel registration" })).toHaveLength(3);
    fireEvent.click(within(row("registered")).getByRole("button", { name: "Cancel registration" }));
    expect(mocks.cancel).toHaveBeenCalledWith(1);
    for (const status of ["attended", "rejected", "cancelled"]) {
      expect(within(row(status)).queryByRole("button", { name: "Cancel registration" })).toBeNull();
    }
  });

  it("disables only the pending row and displays its cancellation error", () => {
    mocks.pending = true;
    mocks.error = new Error("Cannot cancel this registration.");
    show();
    expect(within(row("registered")).getByRole("button", { name: "Cancel registration" })).toBeDisabled();
    expect(within(row("waitlisted")).getByRole("button", { name: "Cancel registration" })).toBeEnabled();
    expect(within(row("registered")).getByRole("alert")).toHaveTextContent("Cannot cancel this registration.");
  });
});
