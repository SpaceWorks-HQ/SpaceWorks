import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { BackupRestorePanel } from "./BackupRestorePanel";
import { RecoveryQuarantinePanel } from "./RecoveryQuarantinePanel";

const { staffRequest } = vi.hoisted(() => ({ staffRequest: vi.fn() }));
vi.mock("../../lib/api", () => ({ staffRequest }));
vi.mock("../../components/SpaceWorksLogo", () => ({ SpaceWorksBadge: () => <span>SpaceWorks</span> }));

function withQueryClient(element: ReactNode) {
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      {element}
    </QueryClientProvider>,
  );
}

beforeEach(() => staffRequest.mockReset());

describe("BackupRestorePanel", () => {
  it("states the purge boundary and shows an all-table restore report", async () => {
    const deadline = new Date(Date.now() + 60_000).toISOString();
    staffRequest.mockImplementation((path: string) => {
      if (path === "/admin/platform/backup-settings") return Promise.resolve({ automatic_backups_enabled: true, retention_days: 30, last_scheduled_at: null, last_success_at: null, last_error: "" });
      if (path === "/admin/platform/restores") return Promise.resolve([{ id: "restore-1", stage: "quiesced" }]);
      if (path === "/admin/platform/restores/restore-1") return Promise.resolve({ id: "restore-1", archive: "archive-1", kind: "rollback_in_place", stage: "quiesced", decision: "pending", decision_deadline_at: deadline, error_detail: "", requested_at: deadline, restore_diff: { tables_compared: 204, tables_changed: 1, tables: [{ table: "accounts_user", security_relevant: true, noisy: false, live: { row_count: 8 }, archive: { row_count: 9 }, row_diff: { removed_count: 1 } }] } });
      return Promise.resolve([]);
    });

    withQueryClient(<BackupRestorePanel makerspaceId={7} isSuperadmin />);

    expect(screen.getAllByText(/outside makerspace purge guarantees/i)).toHaveLength(2);
    expect(await screen.findByText(/204 tables compared; 1 differ/i)).toBeVisible();
    expect(screen.getByText(/accounts_user/)).toBeVisible();
    expect(screen.getByText(/security-relevant/)).toBeVisible();
    expect(screen.getByRole("button", { name: "Abort safely" })).toBeEnabled();
  });

  it("persists operator retention settings", async () => {
    staffRequest.mockImplementation((path: string, options?: RequestInit) => {
      if (path === "/admin/platform/backup-settings" && options?.method === "PATCH") return Promise.resolve({ automatic_backups_enabled: false, retention_days: 45, last_scheduled_at: null, last_success_at: null, last_error: "" });
      if (path === "/admin/platform/backup-settings") return Promise.resolve({ automatic_backups_enabled: false, retention_days: 30, last_scheduled_at: null, last_success_at: null, last_error: "" });
      return Promise.resolve([]);
    });
    withQueryClient(<BackupRestorePanel makerspaceId={7} isSuperadmin />);
    const input = await screen.findByRole("spinbutton", { name: /archive retention/i });
    fireEvent.change(input, { target: { value: "45" } });
    fireEvent.blur(input);
    await waitFor(() => expect(staffRequest).toHaveBeenCalledWith(
      "/admin/platform/backup-settings",
      { method: "PATCH", body: JSON.stringify({ retention_days: 45 }) },
    ));
  });
});

describe("RecoveryQuarantinePanel", () => {
  it("sends the exact displayed residual-risk acknowledgement", async () => {
    staffRequest.mockResolvedValue({ mode: "normal" });
    const risk = "Exact residual risk statement";
    withQueryClient(<RecoveryQuarantinePanel state={{ mode: "quarantined", quarantine_reason: "Disaster restore", quarantined_at: null, residual_risk: risk }} onAcknowledged={() => undefined} />);
    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.click(screen.getByRole("button", { name: "Lift quarantine" }));
    await waitFor(() => expect(staffRequest).toHaveBeenCalledWith(
      "/recovery",
      { method: "POST", body: JSON.stringify({ acknowledgement: risk }) },
    ));
  });
});
