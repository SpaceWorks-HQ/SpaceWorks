import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { EvidenceRetentionPanel } from "./EvidenceRetentionPanel";


const { staffRequest } = vi.hoisted(() => ({ staffRequest: vi.fn() }));

vi.mock("../../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../../lib/api")>("../../lib/api");
  return { ...actual, staffRequest };
});

const policy = {
  makerspace_id: 7,
  platform_default_days: 365,
  override_days: null,
  effective_days: 365,
  object_expiry_enabled: false,
};

function renderPanel() {
  staffRequest.mockImplementation(async (path: string, init?: RequestInit) => {
    if (path.endsWith("/preview")) {
      return {
        as_of: "2026-09-02T10:00:00Z",
        policy_days: 365,
        cutoff: "2025-09-02T10:00:00Z",
        object_candidates: 4,
        candidate_bytes: 2_097_152,
        has_more: false,
      };
    }
    if (init?.method === "PATCH") {
      return { ...policy, override_days: 90, effective_days: 90 };
    }
    return policy;
  });
  return render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <EvidenceRetentionPanel makerspaceId={7} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  staffRequest.mockReset();
});

describe("EvidenceRetentionPanel", () => {
  it("shows inherited disabled state and the object-only expiry warning", async () => {
    renderPanel();

    expect(await screen.findByText(/Inherited platform default: 365 days/i)).toBeVisible();
    expect(screen.getByText(/Automatic expiry is disabled/i)).toBeVisible();
    expect(screen.getByText(/Photo metadata and audit history remain immutable/i)).toBeVisible();
    expect(await screen.findByText(/4 photo objects \(2 MB\)/i)).toBeVisible();
  });

  it("sends the numeric tenant override", async () => {
    renderPanel();
    const input = await screen.findByRole("spinbutton", { name: "Retention days" });
    fireEvent.change(input, { target: { value: "90" } });
    fireEvent.click(screen.getByRole("button", { name: "Save override" }));

    await waitFor(() => expect(staffRequest).toHaveBeenCalledWith(
      "/admin/makerspaces/7/evidence-retention",
      { method: "PATCH", body: JSON.stringify({ object_retention_days: 90 }) },
    ));
  });
});
