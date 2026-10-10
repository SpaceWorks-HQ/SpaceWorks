import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { MembershipPagination } from "./MembershipPagination";

describe("MembershipPagination", () => {
  it("uses the server's next/previous availability and moves one page", () => {
    const page = vi.fn();
    const { rerender } = render(<MembershipPagination label="members" page={1} next="next" previous={null} fetching={false} onPage={page} />);
    expect(screen.getByText("Previous members")).toBeDisabled();
    fireEvent.click(screen.getByText("Next members")); expect(page).toHaveBeenCalledWith(2);
    rerender(<MembershipPagination label="members" page={2} next={null} previous="previous" fetching onPage={page} />);
    expect(screen.getByText("Previous members")).toBeDisabled(); expect(screen.getByText("Next members")).toBeDisabled();
  });
});
