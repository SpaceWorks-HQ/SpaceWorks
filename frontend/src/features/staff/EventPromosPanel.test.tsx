import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { EventPromosPanel } from "./EventPromosPanel";

const { staffRequest } = vi.hoisted(() => ({ staffRequest: vi.fn() }));
vi.mock("../../lib/api", () => ({ staffRequest }));
beforeEach(() => { staffRequest.mockReset(); });
it("creates a fixed discount with a named code and hides the one-time result", async () => {
  staffRequest.mockImplementation((_path, options) => Promise.resolve(options?.method === "POST" ? { id: 1, code: "WELCOME2026" } : { count: 0, next: null, previous: null, results: [] }));
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><EventPromosPanel eventId={4} /></QueryClientProvider>);
  fireEvent.change(screen.getByLabelText("Discount type"), { target: { value: "amount" } });
  fireEvent.change(screen.getByLabelText("Amount discount"), { target: { value: "8.00" } });
  fireEvent.change(screen.getByLabelText("Code (optional)"), { target: { value: "WELCOME2026" } });
  fireEvent.click(screen.getByRole("button", { name: "Create promo code" }));
  expect(await screen.findByText("WELCOME2026")).toBeVisible();
  expect(staffRequest).toHaveBeenCalledWith("/admin/events/4/promo-codes/", expect.objectContaining({ body: JSON.stringify({ amount_off: "8.00", code: "WELCOME2026", max_uses: 1, expires_at: null }) }));
  fireEvent.click(screen.getByRole("button", { name: "Hide code" }));
  expect(screen.queryByText("WELCOME2026")).toBeNull();
});
