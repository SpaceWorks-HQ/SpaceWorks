import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { MakerspaceArchiveRequest } from "../../generated/api";
import { StructuredApiError } from "../../lib/api";
import { MakerspaceArchiveRequestPanel } from "./MakerspaceArchiveRequestPanel";

const { staffRequest } = vi.hoisted(() => ({ staffRequest: vi.fn() }));

vi.mock("../../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../../lib/api")>("../../lib/api");
  return { ...actual, staffRequest };
});

const pendingRequest: MakerspaceArchiveRequest = {
  id: 41,
  makerspace: 7,
  requested_by: 12,
  requested_by_username: "space-manager",
  requested_at: "2026-08-11T08:30:00Z",
  resolved_by: null,
  resolved_by_username: null,
  resolved_at: null,
  reason: "The workshop is closing at the end of the month.",
  resolution_note: "",
  status: "pending",
};

beforeEach(() => {
  staffRequest.mockReset();
});

function renderPanel() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MakerspaceArchiveRequestPanel makerspaceId={7} canManageMakerspace />
    </QueryClientProvider>,
  );
}

describe("MakerspaceArchiveRequestPanel", () => {
  it("shows the empty state and files a bounded reason", async () => {
    staffRequest.mockImplementation(async (_path: string, options?: RequestInit) =>
      options?.method === "POST" ? pendingRequest : []);
    renderPanel();

    const reason = await screen.findByLabelText("Reason for archival");
    expect(reason).toHaveAttribute("maxlength", "2000");
    expect(screen.getByText("No resolved archive requests.")).toBeVisible();
    expect(screen.getByText(/filing a request does not archive anything/i)).toBeVisible();

    fireEvent.change(reason, { target: { value: "  We are ending operations.  " } });
    fireEvent.click(screen.getByRole("button", { name: "Request archival" }));

    await waitFor(() => expect(staffRequest).toHaveBeenCalledWith(
      "/admin/makerspace/7/archive-requests",
      { method: "POST", body: JSON.stringify({ reason: "We are ending operations." }) },
    ));
  });

  it("renders a pending request with its withdraw action", async () => {
    staffRequest.mockResolvedValue([pendingRequest]);
    renderPanel();

    expect(await screen.findByText(pendingRequest.reason)).toBeVisible();
    expect(screen.getByText(/filed by space-manager/i)).toBeVisible();
    expect(screen.getByRole("button", { name: "Withdraw" })).toBeVisible();
    expect(screen.queryByLabelText("Reason for archival")).not.toBeInTheDocument();
  });

  it("translates the archive cooldown error code into readable copy", async () => {
    staffRequest.mockImplementation((_path: string, options?: RequestInit) => {
      if (options?.method === "POST") {
        return Promise.reject(new StructuredApiError(409, {
          detail: "Archive request cooldown is active.",
          code: "archive_request_cooldown",
        }));
      }
      return Promise.resolve([]);
    });
    renderPanel();

    fireEvent.change(await screen.findByLabelText("Reason for archival"), {
      target: { value: "We no longer operate this location." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Request archival" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Please wait one hour after the last archive request before filing another.",
    );
    expect(screen.queryByText("archive_request_cooldown")).not.toBeInTheDocument();
  });
});
