import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AuditVerificationStatus, verificationVerdict, type VerificationRun } from "./AuditVerificationStatus";

const { staffRequest } = vi.hoisted(() => ({ staffRequest: vi.fn() }));
vi.mock("../../../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../../../lib/api")>("../../../lib/api");
  return { ...actual, staffRequest };
});

const accepted = {
  id: 42, state: "QUEUED", deduplicated: false,
  status_url: "/api/v1/admin/makerspace/7/audit-verifications/42",
};
const coverage: VerificationRun["coverage"] = {
  attempt: 1, chain_status: "locally_verified", anchor_status: "externally_anchored",
  row_count: 2, mac_valid_count: 2, unattested_count: 0, mac_invalid_count: 0,
  mac_unavailable_count: 0, unbatched_count: 0, local_batch_verified_count: 2,
  batch_invalid_count: 0, batch_unavailable_count: 0, externally_anchored_count: 2,
};
function run(state = "SUCCEEDED", overrides: Partial<VerificationRun["coverage"]> = {}): VerificationRun {
  return { id: 42, state, terminal: ["SUCCEEDED", "INCOMPLETE", "FAILED", "TIMED_OUT"].includes(state),
    coverage: { ...coverage, ...overrides } };
}
function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const invalidate = vi.spyOn(client, "invalidateQueries");
  const view = render(
    <QueryClientProvider client={client}>
      <AuditVerificationStatus makerspaceId="7" params={{ makerspace: "7", action: "request.issued", actor: "2",
        target_type: "hardware_requests.hardwarerequest", target_id: "9", start: "2026-10-01T00:00:00Z", end: "2026-10-02T00:00:00Z" }} />
    </QueryClientProvider>,
  );
  return { ...view, invalidate };
}
async function advance(ms = 10) {
  await act(async () => { await vi.advanceTimersByTimeAsync(ms); });
}
function statusCalls() {
  return staffRequest.mock.calls.filter(([, options]) => options?.method !== "POST");
}

describe("AuditVerificationStatus", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    staffRequest.mockReset();
    staffRequest.mockImplementation((_path: string, options?: RequestInit) =>
      Promise.resolve(options?.method === "POST" ? accepted : run()));
  });
  afterEach(() => { cleanup(); vi.useRealTimers(); });

  it("posts the complete filter snapshot and polls the returned status URL", async () => {
    const { invalidate } = mount();
    fireEvent.click(screen.getByRole("button", { name: "Verify these entries" }));
    await advance();
    expect(JSON.parse(staffRequest.mock.calls[0][1].body)).toEqual({
      action: "request.issued", actor: "2", target_type: "hardware_requests.hardwarerequest", target_id: "9",
      start: "2026-10-01T00:00:00Z", end: "2026-10-02T00:00:00Z",
    });
    expect(statusCalls()[0][0]).toBe("/admin/makerspace/7/audit-verifications/42");
    expect(screen.getByText("All entries fully verified.")).toBeInTheDocument();
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["audit"] });
  });

  it("disables duplicate submission while the first status response is pending", async () => {
    staffRequest.mockImplementation((_path: string, options?: RequestInit) =>
      options?.method === "POST" ? Promise.resolve(accepted) : new Promise(() => {}));
    mount();
    fireEvent.click(screen.getByRole("button", { name: "Verify these entries" }));
    await advance();
    expect(screen.getByRole("button", { name: "Verify these entries" })).toBeDisabled();
    expect(screen.getByText("Loading verification status…")).toBeInTheDocument();
  });

  it("polls QUEUED, RUNNING and RETRYING then stops at INCOMPLETE", async () => {
    const states = [run("QUEUED"), run("RUNNING"), run("RETRYING"), run("INCOMPLETE", { anchor_status: "unavailable", externally_anchored_count: 0 })];
    staffRequest.mockImplementation((_path: string, options?: RequestInit) =>
      Promise.resolve(options?.method === "POST" ? accepted : states.shift()));
    mount();
    fireEvent.click(screen.getByRole("button", { name: "Verify these entries" }));
    await advance();
    for (let i = 0; i < 3; i++) await advance(3000);
    expect(statusCalls()).toHaveLength(4);
    expect(screen.getByText(/verification coverage is incomplete/)).toBeInTheDocument();
    expect(screen.getByText(/Coverage gaps: external anchor unavailable/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Verify these entries" })).toBeEnabled();
    await advance(9000);
    expect(statusCalls()).toHaveLength(4);
  });

  it.each(["SUCCEEDED", "FAILED", "TIMED_OUT"])("stops polling on %s", async (state) => {
    staffRequest.mockImplementation((_path: string, options?: RequestInit) =>
      Promise.resolve(options?.method === "POST" ? accepted : run(state)));
    mount();
    fireEvent.click(screen.getByRole("button", { name: "Verify these entries" }));
    await advance();
    await advance(9000);
    expect(statusCalls()).toHaveLength(1);
    expect(screen.getByRole("button", { name: "Verify these entries" })).toBeEnabled();
  });

  it("stops polling when unmounted", async () => {
    staffRequest.mockImplementation((_path: string, options?: RequestInit) =>
      Promise.resolve(options?.method === "POST" ? accepted : run("RUNNING")));
    const { unmount } = mount();
    fireEvent.click(screen.getByRole("button", { name: "Verify these entries" }));
    await advance();
    unmount();
    await advance(9000);
    expect(statusCalls()).toHaveLength(1);
  });

  it("shows admission errors", async () => {
    staffRequest.mockRejectedValue(new Error("Another verification is running."));
    mount();
    fireEvent.click(screen.getByRole("button", { name: "Verify these entries" }));
    await advance();
    expect(screen.getByText("Another verification is running.")).toBeInTheDocument();
  });

  it("shows status errors and lets staff retry reading the accepted run", async () => {
    staffRequest.mockResolvedValueOnce(accepted).mockRejectedValueOnce(new Error("Status unavailable."))
      .mockResolvedValueOnce(run());
    mount();
    fireEvent.click(screen.getByRole("button", { name: "Verify these entries" }));
    await advance();
    expect(screen.getByText(/Status unavailable/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Retry status" }));
    await advance();
    expect(screen.getByText("All entries fully verified.")).toBeInTheDocument();
  });

  it("enumerates aggregate gaps and withholds staff diagnostics", async () => {
    staffRequest.mockResolvedValueOnce(accepted).mockResolvedValueOnce({
      ...run("INCOMPLETE", { unattested_count: 1, mac_valid_count: 1, mac_unavailable_count: 1, unbatched_count: 1,
        batch_unavailable_count: 1, chain_status: "unavailable", anchor_status: "not_configured" }),
      failure_code: "verification_bounds_exceeded", first_audit_log_id: 999999,
    });
    const { container } = mount();
    fireEvent.click(screen.getByRole("button", { name: "Verify these entries" }));
    await advance();
    expect(screen.getByText(/Coverage gaps: 1 unattested, 1 MAC unavailable, 1 not yet in a signed batch, 1 batch unavailable, scope chain unavailable, external anchor not configured/)).toBeInTheDocument();
    expect(container.textContent).not.toMatch(/verification_bounds_exceeded|999999/);
  });
});

describe("coverage verdict", () => {
  it("never upgrades an incomplete, empty, unavailable or invalid run to fully verified", () => {
    expect(verificationVerdict(run("INCOMPLETE"))).toContain("coverage is incomplete");
    expect(verificationVerdict(run("SUCCEEDED", { row_count: 0 }))).toContain("coverage is incomplete");
    expect(verificationVerdict(run("SUCCEEDED", { chain_status: "unavailable" }))).toContain("coverage is incomplete");
    expect(verificationVerdict(run("SUCCEEDED", { batch_invalid_count: 1 }))).toContain("Integrity problems");
    expect(verificationVerdict(run("SUCCEEDED", { anchor_status: "invalid" }))).toContain("Integrity problems");
  });
});
