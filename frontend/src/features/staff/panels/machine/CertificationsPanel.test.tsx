import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { staffRequest } from "../../../../lib/api";
import { CertificationsPanel } from "./CertificationsPanel";

vi.mock("../../../../lib/api", () => ({ staffRequest: vi.fn() }));
const cert = { id: 10, machine_type: 2, name: "Laser induction", description: "Safety", validity_days: 30, is_active: true, is_required_for_booking: true, is_required_for_service: false };
const grant = { id: 20, member_name: "Member", membership: 5, is_live: true, granted_at: "2026-10-01T10:00:00Z", expires_at: "2026-11-01T10:00:00Z", revoked_at: null, notes: "Trained" };

function show() {
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })}><CertificationsPanel makerspaceId={1} machineTypeId={2} /></QueryClientProvider>);
}

describe("certification administration", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(staffRequest).mockImplementation(async (path) => {
      if (path.includes("/members")) return { count: 1, next: null, previous: null, results: [{ id: 5, name: "Member" }] };
      if (path.includes("/grants?")) return { count: 1, next: null, previous: null, results: [grant] };
      if (path.includes("certification-types?")) return { count: 2, next: null, previous: null, results: [cert, { ...cert, id: 11, machine_type: 3, name: "Other type" }] };
      return cert;
    });
  });
  it("shows this type's training roster and renews through the audited endpoint", async () => {
    show();
    expect(await screen.findByText("Laser induction")).toBeVisible();
    expect(screen.queryByText("Other type")).toBeNull();
    fireEvent.click(screen.getByText("View grants"));
    expect(await screen.findByText("Trained")).toBeVisible();
    fireEvent.click(screen.getByText("Renew"));
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent("previous record stays in history");
    fireEvent.click(within(dialog).getByText("Renew"));
    await waitFor(() => expect(staffRequest).toHaveBeenCalledWith("/admin/certification-grants/20/renew", { method: "POST", body: JSON.stringify({ notes: "" }) }));
  });
  it("shows a failed list as an error without claiming there are no types", async () => {
    vi.mocked(staffRequest).mockRejectedValue(new Error("Network unavailable"));
    show();
    expect(await screen.findByRole("alert")).toHaveTextContent("Network unavailable");
    expect(screen.queryByText("No certifications defined for this machine type.")).toBeNull();
  });
  it("loads every type page and pages through grant history", async () => {
    vi.mocked(staffRequest).mockImplementation(async (path) => {
      if (path.includes("/members")) return { count: 0, next: null, previous: null, results: [] };
      if (path.includes("/grants?page=2")) return { count: 25, next: null, previous: "page1", results: [{ ...grant, id: 21, notes: "Earlier training" }] };
      if (path.includes("/grants?")) return { count: 25, next: "page2", previous: null, results: [grant] };
      if (path.endsWith("certification-types?page=1")) return { count: 25, next: "page2", previous: null, results: [{ ...cert, id: 11, machine_type: 3, name: "Other type" }] };
      return { count: 25, next: null, previous: "page1", results: [cert] };
    });
    show();
    expect(await screen.findByText("Laser induction")).toBeVisible();
    expect(staffRequest).toHaveBeenCalledWith("/admin/makerspace/1/certification-types?page=2");
    fireEvent.click(screen.getByText("View grants"));
    expect(await screen.findByText("Trained")).toBeVisible();
    fireEvent.click(screen.getByText("More grants"));
    expect(await screen.findByText("Earlier training")).toBeVisible();
    expect(staffRequest).toHaveBeenCalledWith("/admin/certification-types/10/grants?page=2");
  });
});
