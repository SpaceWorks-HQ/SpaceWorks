import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import { SetupChecklist } from "./SetupChecklist";
import { setupSteps, type SetupState } from "./setupChecklistState";

const { staffRequest } = vi.hoisted(() => ({ staffRequest: vi.fn() }));
vi.mock("../../lib/api", () => ({ staffRequest }));
const state: SetupState = { profile_set: false, hours_set: false, first_item_added: false, staff_invited: false, modules_chosen: false };
const space = { id: 7, name: "Forge", slug: "forge", public_code: "FORG", telegram_group_chat_id: "", frontend_domain: null, hidden_from_central_directory: false, enabled_modules: ["public_inventory"] };
function mount(id = 7) {
  return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><MemoryRouter><SetupChecklist key={id} makerspace={{ ...space, id }} owner="manager" allowedTabs={["inventory", "settings", "users"]} guestOnly={false} singleTenantLocked={false} /></MemoryRouter></QueryClientProvider>);
}
beforeEach(() => { localStorage.clear(); staffRequest.mockReset(); staffRequest.mockResolvedValue(state); });
it("derives completion from real state and omits inventory when its module is off", () => {
  expect(setupSteps({ ...state, hours_set: true }, []).map(step => [step.key, step.complete])).toEqual([["profile_set", false], ["hours_set", true], ["staff_invited", false], ["modules_chosen", false]]);
});
it("links permitted setup actions and shows an administrator hint for forbidden modules", async () => {
  mount();
  expect(await screen.findByRole("link", { name: "Add your first item" })).toHaveAttribute("href", "/m/forge/admin/inventory");
  expect(screen.getByText("Choose modules · ask an administrator")).toBeVisible();
  expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
});
it("dismisses per makerspace and keeps another makerspace visible", async () => {
  const first = mount(); await screen.findByRole("link", { name: "Set opening hours" });
  fireEvent.click(screen.getByRole("button", { name: "Dismiss setup checklist" })); first.unmount();
  const again = mount(); expect(screen.queryByText("Set up Forge")).not.toBeInTheDocument(); again.unmount();
  mount(8); expect(await screen.findByRole("link", { name: "Set opening hours" })).toBeVisible();
});
it("hides a completed checklist", async () => {
  staffRequest.mockResolvedValue(Object.fromEntries(Object.keys(state).map(key => [key, true])));
  mount();
  await vi.waitFor(() => expect(screen.queryByText("Set up Forge")).not.toBeInTheDocument());
});
