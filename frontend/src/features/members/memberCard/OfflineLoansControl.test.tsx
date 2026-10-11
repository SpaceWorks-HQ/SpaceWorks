import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, expect, it } from "vitest";
import { OfflineLoansControl } from "./OfflineLoansControl";
import { rememberOfflineCardOwner } from "./offlineCard";
import { readOfflineLoans } from "./offlineLoans";

const token = (user_id: number) => `header.${btoa(JSON.stringify({ user_id }))}.signature`;
const loans = [{ label: "Drill", checked_out_at: "2026-10-10T00:00:00Z", due_at: null }];
beforeEach(() => {
  localStorage.clear(); window.history.replaceState(null, "", "/m/lab/member");
  rememberOfflineCardOwner(token(1));
});

it("does not automatically copy the previous member's opt-in into a switched account", () => {
  const { rerender } = render(<OfflineLoansControl space="lab" loans={loans} />);
  fireEvent.click(screen.getByRole("checkbox"));
  expect(readOfflineLoans()?.owner).toBe("1");
  rememberOfflineCardOwner(token(2));
  rerender(<OfflineLoansControl space="lab" loans={[...loans]} />);
  expect(screen.getByRole("checkbox")).not.toBeChecked();
  expect(readOfflineLoans()).toBeNull();
});

it("refreshes saved loans for the same owner and erases them when the owner opts out", () => {
  const { rerender } = render(<OfflineLoansControl space="lab" loans={loans} />);
  fireEvent.click(screen.getByRole("checkbox"));
  rerender(<OfflineLoansControl space="lab" loans={[]} />);
  expect(readOfflineLoans()?.loans).toEqual([]);
  fireEvent.click(screen.getByRole("checkbox"));
  expect(readOfflineLoans()).toBeNull();
});
