import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { EventPrice } from "./EventPrice";

const ticket = { id: 1, name: "Public", amount: "25.00", audience: "public" as const, spots_left: 5 };
describe("event tier prices", () => {
  it("shows paid tier price even when the legacy amount is zero", () => {
    render(<EventPrice amount="0" currency="inr" tickets={[ticket]} ticketRequired />);
    expect(screen.getByText("25.00 INR")).toBeVisible();
    expect(screen.queryByText("Free")).toBeNull();
  });
  it("shows range starting at free when there is a free tier", () => {
    render(<EventPrice amount="100" currency="inr" tickets={[ticket, { ...ticket, id: 2, amount: "0" }]} />);
    expect(screen.getByText("From Free")).toBeVisible();
  });
  it("does not advertise a free fallback when member tiers are unavailable", () => {
    render(<EventPrice amount="0" currency="inr" tickets={[]} ticketRequired />);
    expect(screen.getByText("No tickets available")).toBeVisible();
  });
});
