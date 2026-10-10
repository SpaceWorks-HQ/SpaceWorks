import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import { StaffLoanRenew } from "./StaffLoanRenew";

const { request } = vi.hoisted(() => ({ request: vi.fn() }));
vi.mock("../../lib/api", () => ({ staffRequest: request }));

it("renews through the staff route and refreshes queues and timeline", async () => {
  request.mockResolvedValue({ renewal_count: 1 });
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  const invalidate = vi.spyOn(client, "invalidateQueries");
  render(<QueryClientProvider client={client}><StaffLoanRenew makerspaceId={7} requestId={12} /></QueryClientProvider>);
  fireEvent.click(screen.getByRole("button", { name: "Renew loan" }));
  await waitFor(() => expect(request).toHaveBeenCalledWith("/admin/makerspace/7/loans/12/renew", { method: "POST", body: "{}" }));
  await waitFor(() => {
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["active", 7] });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["direct-loans", 7] });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["request-timeline", 12] });
  });
});
