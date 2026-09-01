import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { StaffDock } from "./StaffDock";
import type { Makerspace } from "./panels/shared";

const { staffRequest } = vi.hoisted(() => ({ staffRequest: vi.fn() }));

vi.mock("../../lib/api", () => ({ staffRequest }));

const makerspace = {
  id: 7,
  name: "Community Lab",
  public_code: "community-lab",
  slug: "community-lab",
  telegram_group_chat_id: "",
  frontend_domain: null,
  hidden_from_central_directory: false,
} as Makerspace;

const defaultProps: React.ComponentProps<typeof StaffDock> = {
  activeMakerspace: makerspace,
  activeTab: "inventory",
  allowedTabs: ["inventory", "qr"],
  guestOnly: false,
  setTab: vi.fn(),
  singleTenantLocked: false,
};

function renderDock(props: Partial<React.ComponentProps<typeof StaffDock>> = {}) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <MemoryRouter initialEntries={["/m/community-lab/admin/inventory"]}>
      <QueryClientProvider client={client}>
        <StaffDock {...defaultProps} {...props} />
      </QueryClientProvider>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  staffRequest.mockReset();
  staffRequest.mockResolvedValue({ count: 0 });
  vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => {
    callback(0);
    return 1;
  });
});

afterEach(() => vi.unstubAllGlobals());

describe("StaffDock", () => {
  it("renders only groups containing permitted tabs and preserves the named navigation landmark", () => {
    renderDock();

    expect(screen.getByRole("navigation", { name: "Staff sections" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Inventory" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Operate" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Admin" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Insights" })).not.toBeInTheDocument();
  });

  it("toggles a popover and closes the previous popover when another group opens", () => {
    renderDock({ allowedTabs: ["requests", "inventory"] });
    const inventoryButton = screen.getByRole("button", { name: "Inventory" });
    const operateButton = screen.getByRole("button", { name: "Operate" });

    fireEvent.click(inventoryButton);
    expect(inventoryButton).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("link", { name: "Inventory" })).toBeInTheDocument();

    fireEvent.click(inventoryButton);
    expect(inventoryButton).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("link", { name: "Inventory" })).not.toBeInTheDocument();

    fireEvent.click(inventoryButton);
    fireEvent.click(operateButton);
    expect(inventoryButton).toHaveAttribute("aria-expanded", "false");
    expect(operateButton).toHaveAttribute("aria-expanded", "true");
    expect(screen.queryByRole("link", { name: "Inventory" })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Requests" })).toBeInTheDocument();
  });

  it("closes on Escape and restores focus to the owning group button", () => {
    renderDock();
    const inventoryButton = screen.getByRole("button", { name: "Inventory" });

    fireEvent.click(inventoryButton);
    const inventoryRow = screen.getByRole("link", { name: "Inventory" });
    inventoryRow.focus();
    expect(inventoryRow).toHaveFocus();

    fireEvent.keyDown(inventoryRow, { key: "Escape" });

    expect(inventoryButton).toHaveAttribute("aria-expanded", "false");
    expect(inventoryButton).toHaveFocus();
    expect(screen.queryByRole("link", { name: "Inventory" })).not.toBeInTheDocument();
  });

  it("closes when the selected row is already the active route", () => {
    const setTab = vi.fn();
    renderDock({ activeTab: "inventory", setTab });
    const inventoryButton = screen.getByRole("button", { name: "Inventory" });

    fireEvent.click(inventoryButton);
    fireEvent.click(screen.getByRole("link", { name: "Inventory" }));

    expect(setTab).toHaveBeenCalledWith("inventory");
    expect(inventoryButton).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("link", { name: "Inventory" })).not.toBeInTheDocument();
  });

  it("marks only the active row as the current page", () => {
    renderDock({ activeTab: "qr" });
    fireEvent.click(screen.getByRole("button", { name: "Inventory" }));

    expect(screen.getByRole("link", { name: "QR Tools" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "Inventory" })).not.toHaveAttribute("aria-current");
  });

  it("requests unread notifications exactly once even when the count renders in two places", async () => {
    staffRequest.mockResolvedValue({ count: 3 });
    renderDock({ activeTab: "notifications", allowedTabs: ["notifications"] });

    const operateButton = await screen.findByRole("button", { name: "Operate, 3 unread" });
    fireEvent.click(operateButton);
    expect(screen.getByRole("link", { name: /Notifications/ })).toHaveTextContent("3");
    await waitFor(() => expect(staffRequest).toHaveBeenCalledTimes(1));
    expect(staffRequest).toHaveBeenCalledWith("/notifications/makerspace/7/unread-count");
  });

  it("does not request unread notifications without permission or an active makerspace", async () => {
    const permittedView = renderDock({ allowedTabs: ["inventory"] });
    await new Promise((resolve) => window.setTimeout(resolve, 0));
    expect(staffRequest).not.toHaveBeenCalled();
    permittedView.unmount();

    renderDock({ activeMakerspace: undefined, allowedTabs: ["notifications"] });
    await new Promise((resolve) => window.setTimeout(resolve, 0));
    expect(staffRequest).not.toHaveBeenCalled();
  });

  it("includes the unread count in the owning group button's accessible name", async () => {
    staffRequest.mockResolvedValue({ count: 3 });
    renderDock({ activeTab: "notifications", allowedTabs: ["notifications"] });

    expect(await screen.findByRole("button", { name: "Operate, 3 unread" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Operate" })).not.toBeInTheDocument();
  });
});
