import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { RequestTimelineBlock } from "./LoanTimeline";

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
});
