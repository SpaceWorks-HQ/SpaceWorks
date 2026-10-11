import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { BookingReschedule } from "./BookingReschedule";
import type { MemberBooking } from "./MyBookings";

const { memberRequest } = vi.hoisted(() => ({ memberRequest: vi.fn() }));
vi.mock("../../lib/api", () => ({ memberRequest }));

it("keeps the editor open on conflict and refreshes booking and availability caches on success", async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const invalidate = vi.spyOn(client, "invalidateQueries");
  const close = vi.fn();
  const booking = { public_token: "own-token", space_name: "Room" } as MemberBooking;
  memberRequest.mockRejectedValueOnce(new Error("This slot is occupied")).mockResolvedValueOnce(booking);
  const { unmount } = render(<QueryClientProvider client={client}><BookingReschedule booking={booking} slug="forge" onClose={close} /></QueryClientProvider>);
  try {
    fireEvent.change(screen.getByLabelText("New start (your local time)"), { target: { value: "2026-10-20T18:00" } });
    fireEvent.change(screen.getByLabelText("New end (your local time)"), { target: { value: "2026-10-20T19:00" } });
    fireEvent.click(screen.getByRole("button", { name: "Save new time" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("This slot is occupied");
    expect(close).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Save new time" }));
    await waitFor(() => expect(close).toHaveBeenCalledOnce());
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["member", "forge"] });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["public-space-availability"] });
    expect(memberRequest.mock.calls[0][0]).toBe("/public/forge/my-bookings/own-token/reschedule/");
  } finally { unmount(); client.clear(); }
});
