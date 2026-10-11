import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { StaffBookingForm } from "./StaffBookingForm";
import type { BookableSpace } from "./bookingsApi";

const { mutate } = vi.hoisted(() => ({ mutate: vi.fn() }));
vi.mock("./staffBookingApi", () => ({
  useBookingEligibleMembers: () => ({ data: { results: [{ member_id: 5, display_name: "Maker" }] } }),
  useStaffCreateBooking: () => ({ mutate, isPending: false, data: { occurrences: [
    { occurrence: 1, starts_at: "2026-10-20T18:00:00Z", booking_id: 9, status: "confirmed", detail: "" },
    { occurrence: 2, starts_at: "2026-10-27T18:00:00Z", booking_id: null, status: "conflict", detail: "Occupied" },
  ] } }),
}));

it("submits a finite recurrence and displays every occurrence conflict", () => {
  const space = { id: 2, custom_form: null, machine_type: null } as BookableSpace;
  const { unmount } = render(<StaffBookingForm makerspaceId={1} space={space} recurringEnabled />);
  try {
    fireEvent.change(screen.getByLabelText("Member"), { target: { value: "5" } });
    fireEvent.change(screen.getByLabelText("Starts (your local time)"), { target: { value: "2026-10-20T18:00" } });
    fireEvent.change(screen.getByLabelText("Ends (your local time)"), { target: { value: "2026-10-20T19:00" } });
    fireEvent.click(screen.getByLabelText("Repeat weekly in makerspace local time"));
    fireEvent.click(screen.getByRole("button", { name: "Create booking" }));
    expect(mutate).toHaveBeenCalledWith(expect.objectContaining({ count: 8, interval_weeks: 1, member_id: 5 }), expect.any(Object));
    expect(screen.getByLabelText("Recurring booking results")).toHaveTextContent("Conflict: Occupied");
  } finally { unmount(); }
});

it("stops sending recurrence fields when the feature is disabled while editing", () => {
  mutate.mockClear();
  const space = { id: 2, custom_form: null, machine_type: null } as BookableSpace;
  const { rerender, unmount } = render(<StaffBookingForm makerspaceId={1} space={space} recurringEnabled />);
  try {
    fireEvent.change(screen.getByLabelText("Member"), { target: { value: "5" } });
    fireEvent.change(screen.getByLabelText("Starts (your local time)"), { target: { value: "2026-10-20T18:00" } });
    fireEvent.change(screen.getByLabelText("Ends (your local time)"), { target: { value: "2026-10-20T19:00" } });
    fireEvent.click(screen.getByLabelText("Repeat weekly in makerspace local time"));
    rerender(<StaffBookingForm makerspaceId={1} space={space} recurringEnabled={false} />);
    fireEvent.click(screen.getByRole("button", { name: "Create booking" }));
    expect(mutate).toHaveBeenCalledOnce();
    expect(mutate.mock.calls[0][0]).not.toHaveProperty("count");
    expect(mutate.mock.calls[0][0]).not.toHaveProperty("interval_weeks");
  } finally { unmount(); }
});
