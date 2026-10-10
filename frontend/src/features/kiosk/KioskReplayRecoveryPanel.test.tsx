import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { staffRequest } from "../../lib/api";
import { StructuredApiError } from "../../lib/api/errors";
import { expectNoA11yViolations } from "../../test/axe";
import { failedReplay } from "./recoveryTestFixtures";
import { recoveryPath } from "./useKioskReplays";
import { KioskReplayRecoveryPanel } from "./KioskReplayRecoveryPanel";

vi.mock("../../lib/api", async (original) => ({ ...await original<typeof import("../../lib/api")>(), staffRequest: vi.fn() }));
const api = vi.mocked(staffRequest);
const list = { count: 1, next: null, previous: null, results: [failedReplay] };

function show() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const invalidation = vi.spyOn(client, "invalidateQueries");
  return { ...render(<QueryClientProvider client={client}><KioskReplayRecoveryPanel makerspaceId={1} /></QueryClientProvider>), client, invalidation };
}
async function selectFailure() {
  fireEvent.click(await screen.findByRole("button", { name: /reviewed issue · Front desk/ }));
  await screen.findByText("Use the current active QR. Ask a manager to replace a revoked QR if needed.");
}

describe("Failed kiosk recovery", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.mockImplementation(async (path) => path === recoveryPath(failedReplay.id) ? failedReplay : list);
  });

  it("loads scoped details, guidance and evidence with accessible controls", async () => {
    const view = show();
    await selectFailure();
    expect(screen.getByText(/Predecessor preceding · succeeded/)).toBeTruthy();
    api.mockResolvedValueOnce({ url: "https://storage.test/signed" });
    fireEvent.click(screen.getByRole("button", { name: "Preview failed evidence" }));
    expect(await screen.findByRole("link", { name: "Open failed evidence photo" })).toHaveAttribute("href", "https://storage.test/signed");
    expect(api).toHaveBeenCalledWith("/admin/evidence/9");
    await expectNoA11yViolations(view.container);
  });

  it("hides preview without permission", async () => {
    api.mockImplementation(async (path) => path === recoveryPath(failedReplay.id) ? { ...failedReplay, can_view_evidence: false } : list);
    show(); await selectFailure();
    expect(screen.queryByRole("button", { name: "Preview failed evidence" })).toBeNull();
  });

  it("reports expired evidence without opening storage", async () => {
    show(); await selectFailure();
    api.mockRejectedValueOnce(new StructuredApiError(410, { object_expired_at: "2026-10-09T10:00:00Z" }));
    fireEvent.click(screen.getByRole("button", { name: "Preview failed evidence" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("under retention policy");
    expect(screen.queryByRole("link", { name: "Open failed evidence photo" })).toBeNull();
  });

  it("requires explicit confirmation and invalidates recovery and handover queues", async () => {
    const { invalidation } = show(); await selectFailure();
    fireEvent.click(screen.getByRole("button", { name: "Acknowledge — no change occurred" }));
    expect(api.mock.calls.some(([path]) => path.endsWith("resolve/"))).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(api.mock.calls.some(([path]) => path.endsWith("resolve/"))).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "Acknowledge — no change occurred" }));
    api.mockImplementation(async (path) => path.endsWith("resolve/") || path === recoveryPath(failedReplay.id)
      ? { ...failedReplay, resolution_code: "acknowledged_no_change", resolved_by_display: "Reviewer" } : list);
    fireEvent.click(screen.getByRole("button", { name: "Confirm acknowledgement" }));
    await screen.findByText(/Resolved: acknowledged no change/);
    expect(api).toHaveBeenCalledWith(`${recoveryPath(failedReplay.id)}resolve/`, {
      method: "POST", body: JSON.stringify({ resolution_code: "acknowledged_no_change" }),
    });
    for (const key of [["kiosk-replays", 1], ["kiosk-replay", failedReplay.id], ["accepted", 1], ["active", 1], ["direct-loans", 1]]) {
      expect(invalidation).toHaveBeenCalledWith({ queryKey: key });
    }
  });

  it("preserves an unresolved failure when review is refused", async () => {
    show(); await selectFailure();
    api.mockRejectedValueOnce(new Error("permission changed"));
    fireEvent.click(screen.getByRole("button", { name: "Acknowledge — no change occurred" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm acknowledgement" }));
    await screen.findByRole("alert");
    expect(screen.queryByText(/Resolved:/)).toBeNull();
  });

  it("uses server next/previous and resets page for resolution filters", async () => {
    api.mockResolvedValue({ ...list, count: 25, next: "server-next" });
    show();
    fireEvent.click(await screen.findByRole("button", { name: "Next failures" }));
    await waitFor(() => expect(api).toHaveBeenCalledWith("/admin/makerspace/1/kiosk-replays/?resolution=unresolved&page=2"));
    fireEvent.change(screen.getByLabelText("Recovery status"), { target: { value: "resolved" } });
    await waitFor(() => expect(api).toHaveBeenCalledWith("/admin/makerspace/1/kiosk-replays/?resolution=resolved&page=1"));
  });

  it("shows loading, empty and error states", async () => {
    let finish: (value: unknown) => void = () => undefined;
    api.mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }));
    show(); expect(screen.getByText("Loading failed handovers…")).toBeTruthy();
    finish({ ...list, count: 0, results: [] });
    await screen.findByText("No retained failures in this view.");
    api.mockRejectedValueOnce(new StructuredApiError(403, {}));
    fireEvent.change(screen.getByLabelText("Recovery status"), { target: { value: "all" } });
    await screen.findByText("Failed handovers could not be loaded.");
  });
});
