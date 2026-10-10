import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { MembershipReasonDialog } from "./MembershipReasonDialog";

describe("MembershipReasonDialog", () => {
  it("requires a reason and sends trimmed text only on confirmation", () => {
    const confirm = vi.fn(); const close = vi.fn();
    render(<MembershipReasonDialog title="Decline membership" pending={false} error={null} onConfirm={confirm} onClose={close} />);
    expect(screen.getByText("Confirm decision")).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Decision reason"), { target: { value: "  Full this term  " } });
    fireEvent.click(screen.getByText("Confirm decision"));
    expect(confirm).toHaveBeenCalledWith("Full this term");
    fireEvent.click(screen.getByText("Cancel")); expect(close).toHaveBeenCalledOnce();
  });
  it("keeps failures visible and prevents repeat submission while saving", () => {
    render(<MembershipReasonDialog title="Revoke" pending error="Could not revoke" onConfirm={vi.fn()} onClose={vi.fn()} />);
    expect(screen.getByRole("alert")).toHaveTextContent("Could not revoke");
    expect(screen.getByText("Saving…")).toBeDisabled();
  });
});
