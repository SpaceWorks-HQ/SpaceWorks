import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { PlatformUpdatePanel } from "./PlatformUpdatePanel";

const { staffRequest } = vi.hoisted(() => ({ staffRequest: vi.fn() }));
vi.mock("../../lib/api", () => ({ staffRequest }));

const settings = {
  automatic_updates_enabled: true,
  channel: "stable",
  status: "idle",
  current_version: "0.5.0-main.42.abcdef123456",
  available_version: "0.5.0-main.43.123456abcdef",
  target_version: "",
  update_requested_at: null,
  last_checked_at: "2026-07-23T10:00:00Z",
  last_updated_at: "2026-07-22T10:00:00Z",
  last_backup_at: "2026-07-22T09:59:00Z",
  last_backup_name: "pre-update-20260722T095900Z.sql.gz",
  last_error: "",
  updated_at: "2026-07-23T10:00:00Z",
  release_notes: "Fixed return evidence validation.",
  release_url: "https://github.com/SpaceWorks-HQ/SpaceWorks/releases/tag/v0.5.0-main.43.123456abcdef",
  running_since: null,
  is_stuck: false,
  pre_update_version: "",
  pre_update_archive: null,
  rollback_restore: null,
  rollback_available: false,
  rollback_refusal: "no_snapshot",
  rollback_refusal_detail: "",
  rollback_active: false,
};

function renderPanel() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <PlatformUpdatePanel />
    </QueryClientProvider>,
  );
}

describe("PlatformUpdatePanel", () => {
  beforeEach(() => {
    staffRequest.mockReset();
    staffRequest.mockImplementation((path: string, options?: RequestInit) => {
      if (path.endsWith("update-now")) return Promise.resolve({ ...settings, status: "queued" });
      if (options?.method === "PATCH") {
        const body = JSON.parse(String(options.body));
        return Promise.resolve({ ...settings, ...body });
      }
      return Promise.resolve(settings);
    });
  });

  it("shows update state and explains both backup boundaries", async () => {
    renderPanel();

    expect(await screen.findByRole("switch", { name: "Automatic updates" })).toBeChecked();
    expect(screen.getByText("On")).toBeInTheDocument();
    expect(screen.getAllByText(/0.5.0-main.43/)).toHaveLength(3);
    expect(screen.getByText(/checks every seven days/i)).toBeInTheDocument();
    expect(screen.getByText(/restore users, settings, inventory, requests, loans, and audit records/i)).toBeInTheDocument();
    expect(screen.getByText(/MinIO and are not inside this database backup/i)).toBeInTheDocument();
    expect(screen.getByText(/automatically returns the application containers/i)).toBeInTheDocument();
    expect(screen.getByText(/pre-update-20260722T095900Z.sql.gz/)).toBeInTheDocument();
  });

  it("persists the automatic-update toggle", async () => {
    renderPanel();
    fireEvent.click(await screen.findByRole("switch", { name: "Automatic updates" }));

    await waitFor(() => expect(staffRequest).toHaveBeenCalledTimes(2));
    expect(staffRequest).toHaveBeenLastCalledWith(
      "/admin/platform/update-settings",
      expect.objectContaining({
        method: "PATCH",
        body: JSON.stringify({ automatic_updates_enabled: false }),
      }),
    );
    expect(await screen.findByText("Off")).toBeInTheDocument();
  });

  it("queues a manual update without exposing host privileges", async () => {
    renderPanel();
    fireEvent.click(await screen.findByRole("button", { name: "Update now" }));

    await waitFor(() =>
      expect(staffRequest).toHaveBeenCalledWith(
        "/admin/platform/update-settings/update-now",
        { method: "POST" },
      ),
    );
    expect(await screen.findByRole("button", { name: "Update queued" })).toBeDisabled();
  });

  it("saves the selected release channel and displays release notes as text", async () => {
    renderPanel();
    const channel = await screen.findByRole("combobox", { name: "Release channel" });
    expect(channel).toHaveValue("stable");
    expect(screen.getByText(settings.release_notes)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "View GitHub release" })).toHaveAttribute("href", settings.release_url);
    fireEvent.change(channel, { target: { value: "beta" } });
    await waitFor(() => expect(staffRequest).toHaveBeenCalledWith(
      "/admin/platform/update-settings", { method: "PATCH", body: JSON.stringify({ channel: "beta" }) },
    ));
    expect(await screen.findByRole("combobox", { name: "Release channel" })).toHaveValue("beta");
  });

  it("renders untrusted release HTML without executing it", async () => {
    staffRequest.mockResolvedValue({ ...settings, release_notes: "<script>alert(1)</script>" });
    const rendered = renderPanel();
    expect(await screen.findByText("<script>alert(1)</script>")).toBeInTheDocument();
    expect(rendered.container.querySelector("script")).toBeNull();
  });

  it("lets a stuck update be recovered and shows the recorded failure", async () => {
    staffRequest.mockImplementation((path: string) => Promise.resolve({
      ...settings, status: path.endsWith("/recover") ? "failed" : "running",
      is_stuck: !path.endsWith("/recover"), last_error: path.endsWith("/recover") ? "Update interrupted" : "",
    }));
    renderPanel();
    fireEvent.click(await screen.findByRole("button", { name: "Recover interrupted update" }));
    expect(await screen.findByText("Update interrupted")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Update now" })).toBeEnabled();
    expect(staffRequest).toHaveBeenCalledWith("/admin/platform/update-settings/recover", { method: "POST" });
  });

  it("requires both rollback confirmations and submits the displayed restore point", async () => {
    const snapshot = { ...settings, rollback_available: true, pre_update_version: settings.current_version, pre_update_archive: "archive-id" };
    staffRequest.mockImplementation((path: string) => {
      if (path.endsWith("/rollback")) return Promise.resolve({ id: "restore-id" });
      if (path.includes("/restores/")) return Promise.resolve({ id: "restore-id", stage: "requested", decision: "pending", restore_diff: {}, error_detail: "", decision_deadline_at: null });
      return Promise.resolve(snapshot);
    });
    renderPanel();
    fireEvent.click(await screen.findByRole("button", { name: "Roll back to pre-update snapshot" }));
    const confirm = screen.getByRole("button", { name: "Confirm rollback" });
    expect(confirm).toBeDisabled();
    fireEvent.click(screen.getByLabelText(/I understand changes/));
    expect(confirm).toBeDisabled();
    fireEvent.click(screen.getByLabelText(/Restore the database and previous/));
    fireEvent.click(confirm);
    await waitFor(() => expect(staffRequest).toHaveBeenCalledWith(
      "/admin/platform/update-settings/rollback", {
        method: "POST", body: JSON.stringify({ archive_id: "archive-id", confirm_version: settings.current_version, confirm_data_loss: true }),
      },
    ));
    expect(await screen.findByText(/Rollback restore: requested/)).toBeInTheDocument();
  });

  it("shows missing snapshot information without offering a destructive action", async () => {
    renderPanel();
    expect(await screen.findByText(/Rollback unavailable \(no_snapshot\)/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Roll back to pre-update snapshot" })).not.toBeInTheDocument();
  });
});
