import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { EventTicketPicker } from "./EventTicketPicker";

describe("event ticket picker", () => {
  it("shows only server-authorized prices and lets a full type join the waitlist", () => {
    const choose = vi.fn();
    render(<EventTicketPicker tickets={[{ id: 2, name: "Public", amount: "25.00", audience: "public", spots_left: 0 }]} value={null} onChange={choose} currency="INR" />);
    expect(screen.getByRole("option", { name: "Public · 25.00 INR · Waitlist" })).toBeEnabled();
    expect(screen.queryByText(/Member/)).toBeNull();
    fireEvent.change(screen.getByLabelText("Ticket type"), { target: { value: "2" } });
    expect(choose).toHaveBeenCalledWith(2);
  });
  it("renders a free member ticket when the server includes it", () => {
    render(<EventTicketPicker tickets={[{ id: 1, name: "Member", amount: "0.00", audience: "member", spots_left: null }]} value={1} onChange={() => {}} currency="INR" />);
    expect(screen.getByRole("option", { name: "Member · Free" })).toBeVisible();
  });
});
