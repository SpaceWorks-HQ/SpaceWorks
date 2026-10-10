import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { MemberDues, MemberTerm } from "./MemberDashboardSections";

describe("MemberTerm", () => {
  it("renders nothing for a member who never held a plan", () => {
    const { container } = render(<MemberTerm term={null} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("shows a current term without a borrowing warning", () => {
    render(<MemberTerm term={{ plan_name: "Monthly", starts_at: "2026-10-01T00:00:00Z", ends_at: "2026-11-01T00:00:00Z", current: true, blocks_borrowing: false }} />);
    expect(screen.getByText("Monthly")).toBeInTheDocument();
    expect(screen.getByText(/Current until/)).toBeInTheDocument();
    expect(screen.queryByText(/Borrowing is paused/)).not.toBeInTheDocument();
  });

  it("explains a lapsed term that blocks borrowing", () => {
    render(<MemberTerm term={{ plan_name: "Yearly", starts_at: "2025-10-01T00:00:00Z", ends_at: "2026-10-01T00:00:00Z", current: false, blocks_borrowing: true }} />);
    expect(screen.getByText(/Ended/)).toBeInTheDocument();
    expect(screen.getByText("Borrowing is paused until your membership is renewed.")).toBeInTheDocument();
  });
});

describe("MemberDues", () => {
  it("lists each currency separately and never adds them", () => {
    render(<MemberDues dues={{ dues_amount: "25.00", outstanding_by_currency: { inr: "500.00", usd: "10.00" } }} />);
    expect(screen.getByText(/500.00 INR/)).toBeInTheDocument();
    expect(screen.getByText(/10.00 USD/)).toBeInTheDocument();
  });

  it("says the balance is unavailable rather than nothing when the ledger failed", () => {
    render(<MemberDues dues={{ dues_amount: "25.00", outstanding_by_currency: null }} />);
    expect(screen.getByText("Outstanding balance is unavailable right now.")).toBeInTheDocument();
    expect(screen.queryByText("Nothing outstanding.")).not.toBeInTheDocument();
  });
});
