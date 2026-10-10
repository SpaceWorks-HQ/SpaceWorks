import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { SavedViewsMenu } from "./SavedViewsMenu";
import { StaffListContext } from "./StaffListContext";

const { request } = vi.hoisted(() => ({ request: vi.fn() }));
vi.mock("../../lib/api", () => ({ staffRequest: request }));
const saved = { id: 3, owner_username: "manager", name: "Drills", entity: "inventory", state: { q: "drill", ordering: "name", page: "2" }, shared: false };
beforeEach(() => { request.mockReset(); request.mockResolvedValue({ count: 1, next: null, previous: null, results: [saved] }); });
function mount(canShare = false) {
  const restore = vi.fn();
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(<QueryClientProvider client={client}><StaffListContext.Provider value={{ ownerName: "manager", canShare }}><SavedViewsMenu makerspaceId={7} entity="inventory" state={{ q: "laser", ordering: "-name", page: "1" }} onRestore={restore} /></StaffListContext.Provider></QueryClientProvider>);
  return restore;
}
describe("SavedViewsMenu", () => {
  it("restores server state and saves a personal view to the selected makerspace", async () => {
    const restore = mount();
    await screen.findByRole("option", { name: "Drills" });
    fireEvent.change(screen.getByRole("combobox", { name: "Saved views" }), { target: { value: "3" } });
    expect(restore).toHaveBeenCalledWith(saved.state);
    fireEvent.click(screen.getByText("Save current view"));
    fireEvent.change(screen.getByLabelText("View name"), { target: { value: "Lasers" } });
    expect(screen.queryByLabelText("Share to this makerspace")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Save view" }));
    await waitFor(() => expect(request).toHaveBeenCalledWith("/admin/makerspaces/7/saved-views", expect.objectContaining({ method: "POST" })));
    const call = request.mock.calls.find(([_url, options]) => options?.method === "POST")!;
    expect(JSON.parse(call[1].body)).toEqual({ name: "Lasers", entity: "inventory", state: { q: "laser", ordering: "-name", page: "1" }, shared: false });
  });

  it("lets a manager publish a view to the makerspace", async () => {
    mount(true); await screen.findByRole("option", { name: "Drills" });
    fireEvent.click(screen.getByText("Save current view"));
    fireEvent.change(screen.getByLabelText("View name"), { target: { value: "Desk" } });
    fireEvent.click(screen.getByLabelText("Share to this makerspace"));
    fireEvent.click(screen.getByRole("button", { name: "Save view" }));
    await waitFor(() => expect(request.mock.calls.some(([_url, options]) => options?.method === "POST" && JSON.parse(options.body).shared)).toBe(true));
  });

  it("returns to page one after deleting the final view on a later page", async () => {
    let removed = false;
    request.mockImplementation(async (url: string, options?: RequestInit) => {
      if (options?.method === "DELETE") { removed = true; return; }
      if (url.includes("page=2")) {
        if (removed) throw new Error("Invalid page.");
        return { count: 25, next: null, previous: "page-one", results: [{ ...saved, id: 25, name: "Last" }] };
      }
      return { count: removed ? 24 : 25, next: removed ? null : "page-two", previous: null, results: [saved] };
    });
    mount();
    fireEvent.click(await screen.findByText("More views"));
    await screen.findByRole("option", { name: "Last" });
    fireEvent.click(screen.getByText("Manage saved views"));
    fireEvent.click(screen.getByRole("button", { name: "Delete Last" }));
    await screen.findByRole("option", { name: "Drills" });
    expect(removed).toBe(true);
    expect(screen.queryByRole("alert")).toBeNull();
  });
});
