import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ChainOfCustodyBlock, RequestTimelineBlock } from "./LoanTimeline";

const { staffRequest } = vi.hoisted(() => ({ staffRequest: vi.fn() }));

vi.mock("../../../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../../../lib/api")>("../../../lib/api");
  return { ...actual, staffRequest };
});

const timeline = {
  request_id: 9,
  limit: 200,
  truncated: false,
  events: [
    { kind: "return_event", at: "2026-10-01T10:00:00Z", actor: null, detail: { id: 1, remark: "ok" }, evidence_id: 12,
      evidence_retention: { state: "expired", object_expired_at: "2026-10-05T10:00:00Z" } },
    { kind: "issue_evidence", at: "2026-10-01T09:00:00Z", actor: null, detail: { id: 2 }, evidence_id: 11, evidence_retention: null },
    { kind: "audit", at: "2026-10-01T11:00:00Z", actor: { username: "jo", role: "requester" },
      detail: { id: 3, action: "request.issued", action_label: "Request issued", meta: { box_id: 4 }, meta_redacted: true, target_link: null },
      evidence_id: null },
  ],
};

describe("RequestTimelineBlock", () => {
  beforeEach(() => { staffRequest.mockReset(); });
  it("renders audit entries and retention state without any photo link", async () => {
    staffRequest.mockResolvedValue(timeline);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { container } = render(
      <QueryClientProvider client={client}>
        <RequestTimelineBlock requestId={9} />
      </QueryClientProvider>,
    );
    expect(await screen.findByText("Request issued")).toBeTruthy();
    expect(screen.getByText(/box_id: 4/)).toBeTruthy();
    expect(screen.getByText(/some details withheld/)).toBeTruthy();
    expect(screen.getByText(/photo bytes expired/)).toBeTruthy();
    // A null retention row is not rendered as "available".
    expect(container.textContent).not.toMatch(/available/i);
    expect(container.querySelector("a[href], img")).toBeNull();
  });

  it("shows expiring retention and truncation while preserving the server event order", async () => {
    staffRequest.mockResolvedValue({ ...timeline, truncated: true, events: [
      { ...timeline.events[0], evidence_retention: { state: "expiring", object_expired_at: null } },
      timeline.events[2],
    ] });
    const { container } = renderTimeline();
    expect(await screen.findByText(/photo scheduled to expire/)).toBeInTheDocument();
    expect(screen.getByText("History truncated at the requested limit.")).toBeInTheDocument();
    const rows = container.querySelectorAll("li");
    expect(rows[0].textContent).toContain("Return event");
    expect(rows[1].textContent).toContain("Request issued");
    expect(staffRequest).toHaveBeenCalledWith("/admin/requests/9/timeline?limit=200");
  });

  it("shows loading then empty state", async () => {
    let resolve!: (data: unknown) => void;
    staffRequest.mockReturnValue(new Promise((done) => { resolve = done; }));
    renderTimeline();
    expect(screen.getByText("Loading...")).toBeInTheDocument();
    resolve({ ...timeline, events: [] });
    expect(await screen.findByText("No timeline events yet.")).toBeInTheDocument();
  });

  it("shows timeline request errors", async () => {
    staffRequest.mockRejectedValue(new Error("Timeline unavailable."));
    renderTimeline();
    expect(await screen.findByText("Timeline unavailable.")).toBeInTheDocument();
  });

  it("loads chain of custody only when opened and renders quantity coverage", async () => {
    staffRequest.mockResolvedValue({ ...timeline, product_id: 5, asset_groups: [], quantity_summary: {
      loan_count: 2, direct_loan_count: 1, issued_quantity: 4, returned_quantity: 2,
      damaged_quantity: 1, missing_quantity: 0, active_quantity: 1,
    } });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={client}><ChainOfCustodyBlock productId={5} /></QueryClientProvider>);
    expect(staffRequest).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Open" }));
    expect(await screen.findByText(/2 reviewed loans \| 1 direct loans/)).toBeInTheDocument();
    expect(screen.getByText("Request issued")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Hide" }));
    expect(screen.queryByText("Request issued")).toBeNull();
  });
});

function renderTimeline() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}><RequestTimelineBlock requestId={9} /></QueryClientProvider>);
}
