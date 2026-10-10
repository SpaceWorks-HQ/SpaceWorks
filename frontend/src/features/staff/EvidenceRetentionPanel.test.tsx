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
  abandoned_upload_cleanup_enabled: false,
  abandoned_upload_platform_default_days: 7,
  abandoned_upload_override_days: null,
  abandoned_upload_effective_days: 7,
  abandoned_upload_global_enabled: false,
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
        abandoned_upload_cutoff: "2026-08-26T10:00:00Z",
        abandoned_upload_candidates: 3,
        abandoned_upload_candidate_bytes: 0,
        abandoned_upload_has_more: false,
        late_write_receipts: 2,
        late_write_receipts_due: 1,
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
    expect(screen.getAllByText(/Attached evidence rows are immutable and are never deleted/i)[0]).toBeVisible();
    expect(screen.queryByText(/Photo metadata and audit history remain immutable/i)).toBeNull();
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

describe("EvidenceRetentionPanel abandoned uploads", () => {
  it("shows the separate default-off cleanup, its global state and the receipt backlog", async () => {
    renderPanel();

    expect(await screen.findByText(/switched off for this deployment/i)).toBeVisible();
    expect(screen.getByRole("checkbox", { name: /never-used uploads/i })).not.toBeChecked();
    expect(screen.getByText(/legacy\) are\s+never eligible/i)).toBeVisible();
    expect(await screen.findByText(/3 never-used uploads are eligible/i)).toBeVisible();
    expect(screen.getByText(/Late-write receipts: 2 \(1 due\)/i)).toBeVisible();
  });

  it("sends exact partial payloads for opt-in and age", async () => {
    renderPanel();
    fireEvent.click(await screen.findByRole("checkbox", { name: /never-used uploads/i }));
    await waitFor(() => expect(staffRequest).toHaveBeenCalledWith(
      "/admin/makerspaces/7/evidence-retention",
      { method: "PATCH", body: JSON.stringify({ abandoned_upload_cleanup_enabled: true }) },
    ));
    const input = screen.getByRole("spinbutton", { name: /Abandoned upload age/i });
    fireEvent.change(input, { target: { value: "14" } });
    fireEvent.click(screen.getByRole("button", { name: "Save age" }));
    await waitFor(() => expect(staffRequest).toHaveBeenCalledWith(
      "/admin/makerspaces/7/evidence-retention",
      { method: "PATCH", body: JSON.stringify({ abandoned_upload_retention_days: 14 }) },
    ));
  });
});
