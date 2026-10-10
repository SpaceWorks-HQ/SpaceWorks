import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { expectNoA11yViolations } from "../../../test/axe";
import { DevicesPanel } from "./DevicesPanel";

const { staffRequest } = vi.hoisted(() => ({ staffRequest: vi.fn() }));
vi.mock("../../../lib/api", () => ({ staffRequest }));
const device = {
  id: "00000000-0000-0000-0000-000000000001", makerspace: 7, name: "Bench printer", kind: "printer",
  status: "active", key_fingerprint: "abcdef0123456789", key_version: 1,
  last_seen_at: null, offline_since: "2026-10-10T10:05:00Z", offline_notified_at: null, offline_threshold_seconds: 300,
};
const enrollment = { enrollment_id: "grant-1", device_id: device.id, purpose: "rotate", token: "one-time-bearer", expires_at: "2026-10-10T11:00:00Z" };
const listing = { count: 1, next: null, previous: null, results: [device] };
function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return { client, ...render(<QueryClientProvider client={client}><DevicesPanel makerspaceId={7} /></QueryClientProvider>) };
}
beforeEach(() => {
  staffRequest.mockReset();
  staffRequest.mockImplementation((path: string, options?: RequestInit) => {
    if (path.endsWith("/enrollments")) return Promise.resolve(enrollment);
    if (path.endsWith("/devices") && options?.method === "POST") return Promise.resolve({ device, enrollment });
    if (path.includes("?page=")) return Promise.resolve(listing);
    return Promise.resolve(device);
  });
});

describe("Devices identity panel", () => {
  it("shows status, shortened fingerprint and accessible controls", async () => {
    const view = mount();
    fireEvent.click(await screen.findByRole("button", { name: "Bench printer" }));
    expect(await screen.findByRole("button", { name: "Rotate key" })).toBeInTheDocument();
    expect(screen.getByText("Offline")).toBeInTheDocument();
    expect(screen.getByText(/abcdef012345\.\.\./)).toBeInTheDocument();
    expect(screen.queryByText("abcdef0123456789")).not.toBeInTheDocument();
    await expectNoA11yViolations(view.container);
  });

  it("keeps enrollment out of query/mutation caches and storage, and Escape discards it", async () => {
    const { client } = mount();
    fireEvent.click(await screen.findByRole("button", { name: "Bench printer" }));
    const rotate = await screen.findByRole("button", { name: "Rotate key" });
    rotate.focus();
    fireEvent.click(rotate);
    const token = await screen.findByLabelText("Enrollment token");
    expect(token).toHaveValue(enrollment.token);
    await waitFor(() => expect(client.getMutationCache().getAll().every((m) => m.state.status === "success")).toBe(true));
    expect(JSON.stringify(client.getQueryCache().getAll().map((q) => q.state.data))).not.toContain(enrollment.token);
    expect(JSON.stringify(client.getMutationCache().getAll().map((m) => m.state))).not.toContain(enrollment.token);
    expect(JSON.stringify(localStorage)).not.toContain(enrollment.token);
    expect(JSON.stringify(sessionStorage)).not.toContain(enrollment.token);
    expect(window.location.href).not.toContain(enrollment.token);
    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(rotate).toHaveFocus();
  });

  it("creates a device and consumes the one-time grant locally", async () => {
    const { client } = mount();
    fireEvent.change(screen.getByLabelText("Device name"), { target: { value: "New label printer" } });
    fireEvent.change(screen.getByLabelText("Device kind"), { target: { value: "label_printer" } });
    fireEvent.click(screen.getByRole("button", { name: "Create device" }));
    expect(await screen.findByLabelText("Enrollment token")).toHaveValue(enrollment.token);
    expect(staffRequest).toHaveBeenCalledWith("/admin/makerspace/7/devices", expect.objectContaining({
      method: "POST", body: JSON.stringify({ name: "New label printer", kind: "label_printer", offline_threshold_seconds: 300 }),
    }));
    expect(JSON.stringify(client.getMutationCache().getAll().map((m) => m.state.data))).not.toContain(enrollment.token);
  });

  it("loads the next page using a tenant query key and invalidates list/detail on save", async () => {
    staffRequest.mockImplementation((path: string) => {
      if (path.includes("?page=1")) return Promise.resolve({ ...listing, count: 25, next: "next" });
      if (path.includes("?page=2")) return Promise.resolve({ ...listing, previous: "previous" });
      return Promise.resolve(device);
    });
    const { client } = mount();
    const invalidate = vi.spyOn(client, "invalidateQueries");
    fireEvent.click(await screen.findByRole("button", { name: "Bench printer" }));
    fireEvent.change(await screen.findByLabelText("Name"), { target: { value: "Renamed" } });
    fireEvent.click(screen.getByRole("button", { name: "Save identity" }));
    await waitFor(() => expect(invalidate).toHaveBeenCalledWith({ queryKey: ["devices", 7] }));
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    await waitFor(() => expect(staffRequest).toHaveBeenCalledWith("/admin/makerspace/7/devices?page=2"));
    expect(client.getQueryData(["devices", 7, "list", 2])).toEqual({ ...listing, previous: "previous" });
  });

  it("shows loading, retry and empty states", async () => {
    staffRequest.mockImplementationOnce(() => Promise.reject(new Error("offline")));
    mount();
    expect(screen.getByText("Loading devices...")).toBeInTheDocument();
    fireEvent.click(await screen.findByRole("button", { name: "Retry devices" }));
    expect(await screen.findByText("Offline")).toBeInTheDocument();
  });

  it("has an empty state and no identity controls without a selected device", async () => {
    staffRequest.mockResolvedValue({ count: 0, next: null, previous: null, results: [] });
    mount();
    expect(await screen.findByText("No devices yet.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Rotate key" })).not.toBeInTheDocument();
  });

  it("requires confirmation before revocation", async () => {
    mount();
    fireEvent.click(await screen.findByRole("button", { name: "Bench printer" }));
    fireEvent.click(await screen.findByRole("button", { name: "Revoke device" }));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(staffRequest.mock.calls.some(([path]) => path.endsWith("/revoke"))).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    await waitFor(() => expect(staffRequest).toHaveBeenCalledWith(`/admin/devices/${device.id}/revoke`, { method: "POST" }));
  });
});
