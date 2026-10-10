import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { CommandPalette } from "./CommandPalette";
import { expectNoA11yViolations } from "../../test/axe";

const { request } = vi.hoisted(() => ({ request: vi.fn() }));
vi.mock("../../lib/api", () => ({ staffRequest: request }));

function Location() { const location = useLocation(); return <output data-testid="path">{location.pathname}{location.search}</output>; }
function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, throwOnError: false, experimental_prefetchInRender: false } } });
  return render(<MemoryRouter initialEntries={["/admin/inventory"]}><QueryClientProvider client={client}>
    <CommandPalette makerspaceId={7} makerspaceSlug="lab" allowedTabs={["inventory", "members"]} ownerName="manager" guestOnly={false} singleTenantLocked={false} /><Location />
  </QueryClientProvider></MemoryRouter>);
}

beforeEach(() => { request.mockReset(); request.mockResolvedValue({ results: [] }); });

describe("CommandPalette", () => {
  it("opens with Ctrl/Cmd+K, moves with arrows/Home/End, activates Enter and restores focus", async () => {
    const { container } = mount();
    const trigger = screen.getByRole("button", { name: /Search and commands/ }); trigger.focus();
    fireEvent.keyDown(document, { key: "k", ctrlKey: true });
    const input = await screen.findByRole("combobox");
    await waitFor(() => expect(input).toHaveFocus());
    expect(input).toHaveAttribute("aria-expanded", "true");
    fireEvent.keyDown(input, { key: "ArrowDown" });
    expect(screen.getByRole("option", { name: "Go to Members" })).toHaveAttribute("aria-selected", "true");
    fireEvent.keyDown(input, { key: "Home" });
    expect(screen.getByRole("option", { name: "Go to Inventory" })).toHaveAttribute("aria-selected", "true");
    fireEvent.keyDown(input, { key: "End" });
    await expectNoA11yViolations(container);
    fireEvent.keyDown(input, { key: "Enter" });
    expect(screen.getByTestId("path")).toHaveTextContent("/admin/members");
    await waitFor(() => expect(trigger).toHaveFocus());
    fireEvent.keyDown(document, { key: "k", metaKey: true });
    expect(await screen.findByRole("combobox")).toBeTruthy();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("combobox")).toBeNull();
  });

  it("searches the selected makerspace and navigates typed hits; excludes forbidden navigation", async () => {
    request.mockResolvedValue({ results: [
      { entity: "members", id: 9, label: "laser-user", tab: "members", query: { id: "9" } },
      { entity: "payments", id: 99, label: "Forbidden", tab: "payments", query: {} },
    ] });
    mount(); fireEvent.click(screen.getByRole("button", { name: /Search and commands/ }));
    const input = await screen.findByRole("combobox");
    fireEvent.change(input, { target: { value: "laser" } });
    await screen.findByRole("option", { name: "Members: laser-user" });
    expect(request).toHaveBeenCalledWith("/admin/search?makerspace_id=7&q=laser", expect.objectContaining({ signal: expect.any(AbortSignal) }));
    expect(screen.queryByText(/Forbidden/)).toBeNull();
    fireEvent.keyDown(input, { key: "Enter" });
    expect(screen.getByTestId("path")).toHaveTextContent("/admin/members?id=9");
  });

  it("handles empty results and errors without losing keyboard navigation", async () => {
    request.mockRejectedValue(new Error("Offline")); mount();
    fireEvent.keyDown(document, { key: "k", ctrlKey: true });
    const input = await screen.findByRole("combobox");
    fireEvent.change(input, { target: { value: "nothing" } });
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Offline"));
    fireEvent.keyDown(input, { key: "ArrowDown" }); fireEvent.keyDown(input, { key: "Enter" });
    expect(input.getAttribute("aria-activedescendant")).toBeNull();
    expect(screen.getByTestId("path").textContent).toBe("/admin/inventory");
    fireEvent.keyDown(document, { key: "Escape" });
  });
});
