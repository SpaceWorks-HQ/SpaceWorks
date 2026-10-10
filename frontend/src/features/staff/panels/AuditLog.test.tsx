import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AuditLog } from "./AuditLog";
import { auditFilterParams, emptyAuditFilters } from "./AuditLogFilters";
import { verificationVerdict, type VerificationRun } from "./AuditVerificationStatus";

const { staffRequest } = vi.hoisted(() => ({ staffRequest: vi.fn() }));

vi.mock("../../../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../../../lib/api")>("../../../lib/api");
  return { ...actual, staffRequest };
});

const page = {
  count: 1,
  next: null,
  previous: null,
  results: [
    {
      id: 5, actor: 2, action: "request.issued", action_label: "Request issued", actor_display: "Jo",
      makerspace: 7, target_type: "hardware_requests.hardwarerequest", target_id: "9",
      meta: { box_id: 4 }, meta_redacted: true, created_at: "2026-10-01T10:00:00Z", target_link: null,
    },
  ],
};

const coverage = {
  attempt: 1, chain_status: "locally_verified", anchor_status: "externally_anchored",
  row_count: 2, mac_valid_count: 2, unattested_count: 0, mac_invalid_count: 0,
  mac_unavailable_count: 0, unbatched_count: 0, local_batch_verified_count: 2,
  batch_invalid_count: 0, batch_unavailable_count: 0, externally_anchored_count: 2,
};

function run(overrides: Partial<VerificationRun> = {}, cov: Partial<typeof coverage> = {}): VerificationRun {
  return { id: 1, state: "SUCCEEDED", terminal: true, coverage: { ...coverage, ...cov }, ...overrides };
}

function renderPanel() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <MemoryRouter><QueryClientProvider client={client}>
      <AuditLog />
    </QueryClientProvider></MemoryRouter>,
  );
}

describe("AuditLog", () => {
  beforeEach(() => {
    staffRequest.mockReset();
    staffRequest.mockImplementation((path: string, options?: RequestInit) => {
      if (options?.method === "POST") return Promise.resolve({ id: 1, state: "QUEUED", deduplicated: false, status_url: "/api/v1/admin/makerspace/7/audit-verifications/1" });
      if (path.includes("/audit-verifications/1")) return Promise.resolve(run());
      return Promise.resolve(page);
    });
  });

  it("renders the label and only the projected metadata", async () => {
    renderPanel();
    expect(await screen.findByText("Request issued")).toBeTruthy();
    expect(screen.getByText(/box_id: 4/)).toBeTruthy();
    expect(screen.getByText(/some details withheld/)).toBeTruthy();
  });

  it("resets to page 1 and sends validated filter names on change", async () => {
    staffRequest.mockImplementation((path: string) => Promise.resolve({ ...page, count: 48,
      next: path.includes("page=2") ? null : "?page=2", previous: path.includes("page=2") ? "?page=1" : null }));
    renderPanel();
    await screen.findByText("Request issued");
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    await waitFor(() => expect(staffRequest.mock.calls[staffRequest.mock.calls.length - 1]?.[0]).toContain("page=2"));
    fireEvent.change(screen.getByLabelText("Action"), { target: { value: "request.issued" } });
    await waitFor(() => {
      const calls = staffRequest.mock.calls; const last = calls[calls.length - 1]?.[0] as string;
      expect(last).toContain("action=request.issued");
      expect(last).toContain("page=1");
    });
  });

  it("requires a makerspace before verifying, then posts the filters without it", async () => {
    renderPanel();
    const button = await screen.findByRole("button", { name: "Verify these entries" });
    expect((button as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(screen.getByLabelText("Makerspace ID"), { target: { value: "7" } });
    fireEvent.change(screen.getByLabelText("Action"), { target: { value: "x.y" } });
    fireEvent.click(screen.getByRole("button", { name: "Verify these entries" }));
    await screen.findByText("All entries fully verified.");
    const post = staffRequest.mock.calls.find(([, options]) => options?.method === "POST");
    expect(post?.[0]).toBe("/admin/makerspace/7/audit-verifications");
    expect(JSON.parse(post?.[1]?.body as string)).toEqual({ action: "x.y" });
  });

  it("clears the old verdict on a filter or makerspace change without polling the old run in another tenant", async () => {
    renderPanel();
    fireEvent.change(screen.getByLabelText("Makerspace ID"), { target: { value: "7" } });
    fireEvent.click(screen.getByRole("button", { name: "Verify these entries" }));
    await screen.findByText("All entries fully verified.");
    fireEvent.change(screen.getByLabelText("Action"), { target: { value: "request.returned" } });
    expect(screen.queryByText("All entries fully verified.")).toBeNull();
    fireEvent.change(screen.getByLabelText("Makerspace ID"), { target: { value: "8" } });
    await waitFor(() => expect(staffRequest.mock.calls[staffRequest.mock.calls.length - 1]?.[0]).toContain("makerspace=8"));
    expect(staffRequest.mock.calls.some(([path]) => path === "/admin/makerspace/8/audit-verifications/1")).toBe(false);
    expect(screen.getByRole("button", { name: "Verify these entries" })).toBeEnabled();
  });

  it("renders audit request errors", async () => {
    staffRequest.mockRejectedValue(new Error("Invalid audit range."));
    renderPanel();
    expect(await screen.findByText("Invalid audit range.")).toBeInTheDocument();
  });
});

describe("verificationVerdict", () => {
  it("never claims full verification without every dimension", () => {
    expect(verificationVerdict(run())).toBe("All entries fully verified.");
    expect(verificationVerdict(run({}, { anchor_status: "not_configured", externally_anchored_count: 0 })))
      .toBe("No invalid entries found; verification coverage is incomplete.");
    expect(verificationVerdict(run({}, { unbatched_count: 1, local_batch_verified_count: 1 })))
      .toBe("No invalid entries found; verification coverage is incomplete.");
    expect(verificationVerdict(run({}, { mac_invalid_count: 1 }))).toBe("Integrity problems were found in this range.");
    expect(verificationVerdict(run({ state: "RUNNING", terminal: false }))).toBe("Verification in progress…");
    expect(verificationVerdict(run({ state: "TIMED_OUT" }))).toBe("Verification did not complete.");
  });
});

describe("auditFilterParams", () => {
  it("maps local dates to an inclusive start and exclusive next-day end", () => {
    const params = auditFilterParams({ ...emptyAuditFilters, start: "2026-10-01", end: "2026-10-01" });
    expect(new Date(params.end).getTime() - new Date(params.start).getTime()).toBe(24 * 3600 * 1000);
  });
});
