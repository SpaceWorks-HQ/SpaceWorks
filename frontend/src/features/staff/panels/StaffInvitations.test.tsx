import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, expect, it, vi } from "vitest";

import { staffRequest } from "../../../lib/api";
import { StaffInvitations } from "./StaffInvitations";
import type { StaffRole } from "./rolesApi";

vi.mock("../../../lib/api", () => ({ staffRequest: vi.fn() }));
const request = vi.mocked(staffRequest);
const role = { id: 7, name: "Front desk", granted_actions: ["issue_request"] } as StaffRole;
const row = { id: 8, email: "person@example.test", role_name: "Front desk", expires_at: "2026-10-20T12:00:00Z", accepted_at: null, revoked_at: null };
const base = "/admin/makerspaces/3/staff-invitations";

beforeEach(() => { request.mockReset(); });

it("creates a scoped invitation, offers the copyable link, and refreshes the list", async () => {
  const delivered = { accept_url: "https://app.example.test/staff-invitations/accept#token=private", delivery_status: "skipped" };
  request.mockImplementation(async (path) => path === base ? delivered : { results: [row], count: 1, next: null, previous: null });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><StaffInvitations msId={3} roles={[role]} /></QueryClientProvider>);
  expect(await screen.findByText(/person@example.test/)).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Email"), { target: { value: "new@example.test" } });
  fireEvent.change(screen.getByLabelText("Role"), { target: { value: "7" } });
  fireEvent.click(screen.getByRole("button", { name: "Invite staff" }));
  expect(await screen.findByLabelText("Invitation link")).toHaveValue(delivered.accept_url);
  expect(request).toHaveBeenCalledWith(base, { method: "POST", body: JSON.stringify({ email: "new@example.test", role_id: 7, expires_in_days: 7 }) });
  await waitFor(() => expect(request.mock.calls.filter(([path]) => path === `${base}?page=1`).length).toBeGreaterThan(1));
});

it("revokes and resends through the selected makerspace's routes", async () => {
  request.mockImplementation(async (path) => path.endsWith("/resend") ? { accept_url: "https://app/#token=rotated", delivery_status: "sent" }
    : path.endsWith("/revoke") ? row : { results: [row], count: 1, next: null, previous: null });
  render(<QueryClientProvider client={new QueryClient()}><StaffInvitations msId={3} roles={[role]} /></QueryClientProvider>);
  fireEvent.click(await screen.findByRole("button", { name: "Resend" }));
  expect(await screen.findByLabelText("Invitation link")).toHaveValue("https://app/#token=rotated");
  fireEvent.click(screen.getByRole("button", { name: "Revoke" }));
  await waitFor(() => expect(request).toHaveBeenCalledWith(`${base}/8/revoke`, { method: "POST" }));
  expect(request).toHaveBeenCalledWith(`${base}/8/resend`, { method: "POST" });
});
