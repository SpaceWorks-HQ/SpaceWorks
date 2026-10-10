import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";

import { useCancelEventRegistration } from "./eventsRegistrationApi";
import { organizedEventKeys } from "./organizedEventsApi";

const { staffRequest } = vi.hoisted(() => ({ staffRequest: vi.fn() }));
vi.mock("../../lib/api", async () => ({
  ...await vi.importActual<typeof import("../../lib/api")>("../../lib/api"), staffRequest,
}));

beforeEach(() => { staffRequest.mockReset(); });

describe("staff cancellation mutation", () => {
  it("posts the registration route and refreshes roster, event counts, eligibility and money", async () => {
    staffRequest.mockResolvedValue({ id: 11, status: "cancelled" });
    const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
    const invalidate = vi.spyOn(client, "invalidateQueries");
    const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>;
    const { result } = renderHook(() => useCancelEventRegistration(7, 3), { wrapper });
    await act(async () => { await result.current.mutateAsync(11); });
    expect(staffRequest).toHaveBeenCalledWith("/admin/event-registrations/11/cancel/", { method: "POST", body: "{}" });
    for (const queryKey of [["event", 3, "registrations"], ["event", 3], ["events", 7, "list"], ["event", 3, "eligible-members"], ["payments", 7], organizedEventKeys.all]) {
      expect(invalidate).toHaveBeenCalledWith({ queryKey });
    }
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
  });
});
