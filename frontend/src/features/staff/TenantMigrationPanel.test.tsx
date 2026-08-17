import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { StructuredApiError } from "../../lib/api";
import { TenantMigrationPanel } from "./TenantMigrationPanel";

const { staffRequest } = vi.hoisted(() => ({ staffRequest: vi.fn() }));
vi.mock("../../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../../lib/api")>("../../lib/api");
  return { ...actual, staffRequest };
});

const digest = "a".repeat(64);
const oldDigest = "b".repeat(64);
const identity = {
  id: 11, username: "ada", email: "ada@example.test", first_name: "Ada",
  last_name: "Maker", display_name: "Ada Maker", phone: "+15550001111",
  date_joined: "2026-01-01T00:00:00Z",
};
const deploymentIdentity = {
  algorithm: "ed25519", deployment_id: "target-deployment", public_key: "public-key",
  fingerprint: "f".repeat(64), age_recipient: "age1target",
};
const baseJob = {
  id: "11111111-1111-1111-1111-111111111111",
  source_archive_digest: digest,
  source_makerspace_id: "7",
  source_makerspace_name: "Forge",
  source_makerspace_slug: "forge",
  source_deployment_id: "source-deployment",
  identity_count: "1",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  expires_at: "2026-01-02T00:00:00Z",
  source_retention_notice: "Archives are outside the purge guarantee.",
};
const pairing = {
  id: "22222222-2222-2222-2222-222222222222",
  migration_id: baseJob.id,
  source_tenant_id: "7",
  archive_digest: digest,
  source_deployment_id: "source-deployment",
  source_fingerprint: "s".repeat(64),
  target_deployment_id: "target-deployment",
  target_fingerprint: "t".repeat(64),
  approved_at: "2026-01-01T00:00:00Z",
};
const receipt = {
  payload: { operation: "source_cutover" },
  signer_fingerprint: "s".repeat(64),
  signature: "signature",
};

type ApiState = {
  closureDigest?: string;
  approvals?: unknown[];
  exports?: unknown[];
  imports?: unknown[];
  pairings?: unknown[];
  post?: (path: string, options?: RequestInit) => Promise<unknown> | undefined;
};

function installApi(state: ApiState = {}) {
  staffRequest.mockImplementation((path: string, options?: RequestInit) => {
    if (options?.method === "POST") {
      const result = state.post?.(path, options);
      if (result) return result;
    }
    if (path.endsWith("/disclosure-closure")) return Promise.resolve({ digest: state.closureDigest ?? digest, identities: [identity] });
    if (path.endsWith("/disclosure-approvals")) return Promise.resolve(state.approvals ?? []);
    if (path.endsWith("/exports")) return Promise.resolve(state.exports ?? []);
    if (path.endsWith("/deployment-identity")) return Promise.resolve(deploymentIdentity);
    if (path.endsWith("/pairings")) return Promise.resolve(state.pairings ?? []);
    if (path.endsWith("/imports")) return Promise.resolve(state.imports ?? []);
    if (path.endsWith("/identity-decisions")) return Promise.resolve([identity]);
    if (path.endsWith("/verification")) return Promise.resolve({
      format_version: 1, target_makerspace_id: 99, imported: { hardware: 4 },
      resolved: { users: 1 }, dropped: {}, identities_linked: 1,
      identities_created: 0, external_references_created: 2,
    });
    if (/\/exports\/[^/]+$/.test(path)) return Promise.resolve(state.exports?.[0] ?? {});
    if (/\/imports\/[^/]+$/.test(path)) return Promise.resolve(state.imports?.[0] ?? {});
    return Promise.resolve({});
  });
}

function renderPanel() {
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })}>
      <TenantMigrationPanel makerspace={{ id: 7, name: "Forge", slug: "forge", public_code: "forge", telegram_group_chat_id: "", frontend_domain: null, hidden_from_central_directory: false }} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  staffRequest.mockReset();
  vi.restoreAllMocks();
});

describe("TenantMigrationPanel disclosure", () => {
  it("renders the exact closure and approves its exact digest and per-person decision", async () => {
    installApi({ post: () => Promise.resolve({ id: "approval", closure_digest: digest, identity_count: "1", approved_count: "1", approved_at: "now" }) });
    renderPanel();

    expect(await screen.findByText("Ada Maker")).toBeVisible();
    expect(screen.getByTestId("closure-digest")).toHaveTextContent(digest);
    fireEvent.click(screen.getByRole("checkbox", { name: /Ada Maker/i }));
    fireEvent.click(screen.getByRole("checkbox", { name: /I reviewed every person/i }));
    fireEvent.click(screen.getByRole("button", { name: "Approve exact closure" }));

    await waitFor(() => expect(staffRequest).toHaveBeenCalledWith(
      "/admin/makerspace/7/tenant-migration/disclosure-approvals",
      { method: "POST", body: JSON.stringify({ digest, decisions: [{ user_id: 11, approved: true }] }) },
    ));
  });

  it("marks a non-revoked approval void when the closure digest changed", async () => {
    installApi({ approvals: [{ id: "old", closure_digest: oldDigest, identity_count: "1", approved_count: "1", approved_at: "now", revoked_at: null }] });
    renderPanel();

    expect(await screen.findByText(/VOID — disclosure closure changed/i)).toBeVisible();
    expect(screen.getByText("REVIEW REQUIRED")).toBeVisible();
    expect(screen.queryByText("APPROVED")).not.toBeInTheDocument();
  });

  it("reads a field error from StructuredApiError.body", async () => {
    installApi({ post: () => Promise.reject(new StructuredApiError(400, {
      detail: "Validation failed.", digest: ["Review the newly computed digest."],
    })) });
    renderPanel();
    await screen.findByText("Ada Maker");
    fireEvent.click(screen.getByRole("checkbox", { name: /I reviewed every person/i }));
    fireEvent.click(screen.getByRole("button", { name: "Approve exact closure" }));
    expect(await screen.findByText("Review the newly computed digest.")).toHaveAttribute("role", "alert");
  });
});

describe("TenantMigrationPanel identity decisions", () => {
  it("submits an explicit resolution and membership disposition per person", async () => {
    const job = { ...baseJob, status: "awaiting_identity" };
    installApi({ imports: [job], post: (path) => path.endsWith("/identity-decisions") ? Promise.resolve({ ...job, status: "ready" }) : undefined });
    renderPanel();
    fireEvent.change(await screen.findByRole("combobox", { name: "Identity resolution for Ada Maker" }), { target: { value: "link_existing" } });
    fireEvent.change(screen.getByRole("spinbutton", { name: "Target user ID for Ada Maker" }), { target: { value: "42" } });
    fireEvent.change(screen.getByRole("combobox", { name: "Membership for Ada Maker" }), { target: { value: "no_membership" } });
    fireEvent.click(screen.getByRole("button", { name: "Submit all identity decisions" }));

    await waitFor(() => expect(staffRequest).toHaveBeenCalledWith(
      `/admin/platform/tenant-migrations/imports/${baseJob.id}/identity-decisions`,
      { method: "POST", body: JSON.stringify({ decisions: [{ source_user_id: "11", identity_resolution: "link_existing", membership_disposition: "no_membership", target_user_id: 42 }] }) },
    ));
  });
});

describe("TenantMigrationPanel cutover", () => {
  const completed = { ...baseJob, status: "completed" };
  const exportJob = {
    id: "export-1", status: "available", closure_digest: digest, archive_digest: digest,
    format_version: 1, source_retention_notice: "Archives are outside the purge guarantee.",
    created_at: "now", expires_at: "later",
  };

  it("keeps a materializing target visibly IMPORTING while objects promote", async () => {
    installApi({ imports: [{ ...baseJob, status: "materializing" }] });
    renderPanel();
    expect(await screen.findByText("IMPORTING")).toBeVisible();
    expect(screen.getByText(/Objects are still promoting/)).toBeVisible();
    expect(screen.getAllByText(/archives are outside the purge guarantee/i).length).toBeGreaterThan(0);
  });

  it("requires tenant-naming confirmations for every destructive cutover action", async () => {
    installApi({ imports: [completed], exports: [exportJob], pairings: [pairing] });
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    renderPanel();
    fireEvent.click(await screen.findByRole("button", { name: "Quiesce Forge" }));
    fireEvent.click(await screen.findByRole("button", { name: "Archive source Forge" }));
    fireEvent.change(await screen.findByLabelText("Source cutover receipt"), { target: { value: JSON.stringify(receipt) } });
    await screen.findByText(/Target makerspace 99/);
    fireEvent.click(screen.getByRole("button", { name: "Activate target Forge" }));
    fireEvent.click(screen.getByRole("button", { name: "Abort target Forge" }));

    expect(confirm).toHaveBeenCalledTimes(4);
    confirm.mock.calls.forEach(([message]) => expect(message).toContain("Forge"));
    expect(staffRequest.mock.calls.filter(([, options]) => options?.method === "POST")).toHaveLength(0);
  });

  it("shows IMPORTING before cutover and ACTIVE only after activation", async () => {
    installApi({ imports: [completed], pairings: [pairing], post: (path) => path.endsWith("/activate") ? Promise.resolve({ message: "active", receipt }) : undefined });
    vi.spyOn(window, "confirm").mockReturnValue(true);
    renderPanel();
    expect(await screen.findByText("IMPORTING")).toBeVisible();
    await screen.findByText("imported");
    expect(screen.getByRole("region", { name: "Import verification report" })).toHaveTextContent("imported");
    fireEvent.change(await screen.findByLabelText("Source cutover receipt"), { target: { value: JSON.stringify(receipt) } });
    fireEvent.click(screen.getByRole("button", { name: "Activate target Forge" }));
    expect(await screen.findByText("ACTIVE")).toBeVisible();
    expect(screen.queryByText("IMPORTING")).not.toBeInTheDocument();
  });

  it("shows ABORTED distinctly and exposes the target abort receipt", async () => {
    installApi({ imports: [completed], pairings: [pairing], post: (path) => path.endsWith("/abort") ? Promise.resolve({ message: "aborted", receipt }) : undefined });
    vi.spyOn(window, "confirm").mockReturnValue(true);
    renderPanel();
    fireEvent.click(await screen.findByRole("button", { name: "Abort target Forge" }));
    expect(await screen.findByText("ABORTED")).toBeVisible();
    expect(screen.getByLabelText(/Target abort receipt/)).toHaveValue(JSON.stringify(receipt, null, 2));
  });
});
