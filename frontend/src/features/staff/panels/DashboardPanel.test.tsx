import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DashboardPanel } from "./DashboardPanel";

const { staffRequest } = vi.hoisted(() => ({ staffRequest: vi.fn() }));

vi.mock("../../../lib/api", () => ({ staffRequest }));

const makerspace = {
  id: 7,
  name: "Forge",
  public_code: "forge",
  slug: "forge",
  telegram_group_chat_id: "",
  frontend_domain: null,
  hidden_from_central_directory: false,
};

function renderPanel(canManageMakerspace = false) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <DashboardPanel
        makerspace={makerspace}
        canManageMakerspace={canManageMakerspace}
      />
    </QueryClientProvider>,
  );
}

beforeEach(() => staffRequest.mockReset());

describe("DashboardPanel scope mode", () => {
  it("renders only server-declared machine tiles in restricted mode", async () => {
    staffRequest.mockResolvedValue({
      scope_mode: "machine",
      pending_prints: 1,
      active_prints: 2,
      prints_awaiting_collection: 3,
      warranty_expiring: 4,
      maintenance_overdue: 5,
    });

    renderPanel();

    await waitFor(() => {
      expect(screen.queryByText("Overdue loans")).not.toBeInTheDocument();
    });
    expect(screen.getByText("Maintenance overdue")).toBeVisible();
    expect(screen.getByText("Pending prints")).toBeVisible();
    expect(screen.getByText("Warranties expiring")).toBeVisible();
    expect(screen.queryByText("Pending requests")).not.toBeInTheDocument();
    expect(screen.queryByText("Out of stock")).not.toBeInTheDocument();
  });

  it("keeps the full dashboard tiles in full mode", async () => {
    staffRequest.mockResolvedValue({ scope_mode: "full", overdue_loans: 2 });

    renderPanel(true);

    expect(await screen.findByText("Overdue loans")).toBeVisible();
    expect(screen.getByText("Pending payments")).toBeVisible();
    expect(screen.getByText("Maintenance overdue")).toBeVisible();
  });
});
