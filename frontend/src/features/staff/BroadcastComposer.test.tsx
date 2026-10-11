import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { BroadcastComposer } from "./BroadcastComposer";

const { staffRequest } = vi.hoisted(() => ({ staffRequest: vi.fn() }));
vi.mock("../../lib/api", () => ({ staffRequest }));
beforeEach(() => staffRequest.mockReset());

it("submits named segment choices and renders the eligible-recipient receipt", async () => {
  staffRequest.mockImplementation(async (_path: string, options?: { method: string }) => options?.method === "POST"
    ? { recipients: 4, broadcast: { id: 1 } }
    : { plans: [{ id: 9, name: "Workshop plan" }], certifications: [{ id: 7, name: "Laser induction" }] });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const { unmount } = render(<QueryClientProvider client={client}><BroadcastComposer makerspaceId={2} /></QueryClientProvider>);
  try {
    await screen.findByRole("option", { name: "Workshop plan" });
    fireEvent.change(screen.getByLabelText("Plan"), { target: { value: "9" } });
    fireEvent.change(screen.getByLabelText("Certification"), { target: { value: "7" } });
    fireEvent.change(screen.getByLabelText("Title"), { target: { value: "Room update" } });
    fireEvent.change(screen.getByLabelText("Message"), { target: { value: "Meet in the annex" } });
    fireEvent.click(screen.getByRole("button", { name: "Send announcement" }));
    await waitFor(() => expect(staffRequest).toHaveBeenCalledWith("/notifications/broadcasts/2", {
      method: "POST", body: JSON.stringify({ title: "Room update", body: "Meet in the annex", plan_id: 9, certification_id: 7 }),
    }));
    await screen.findByText(/queued for 4 eligible members/);
  } finally { unmount(); client.clear(); }
});
