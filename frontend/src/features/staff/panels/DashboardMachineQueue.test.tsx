import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import { DashboardMachineQueue, isDashboardMachineQueue } from "./DashboardMachineQueue";
const { staffRequest, getMachineTypes } = vi.hoisted(() => ({ staffRequest: vi.fn(), getMachineTypes: vi.fn() }));
vi.mock("../../../lib/api", () => ({ staffRequest }));
vi.mock("../machinesApi", () => ({ getMachineTypes, machineKeys: { types: (id: number) => ["types", id] }, collectionResults: (rows: unknown[]) => rows ?? [] }));
function mount(queue: string, enabled = true) {
  return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><MemoryRouter initialEntries={[`/m/forge/admin/machines?work_queue=${queue}&page=2`]}><DashboardMachineQueue makerspaceId={7} slug="forge" single={false} guest={false} enabled={enabled} /></MemoryRouter></QueryClientProvider>);
}
beforeEach(() => { staffRequest.mockReset(); getMachineTypes.mockReset(); });
it("recognizes only explicit work queues from URL state", () => {
  expect(isDashboardMachineQueue("maintenance_overdue")).toBe(true);
  expect(isDashboardMachineQueue("toString")).toBe(false);
  expect(isDashboardMachineQueue("__proto__")).toBe(false);
});
it("filters print jobs by status and the global built-in type ID, excluding a tenant slug collision", async () => {
  getMachineTypes.mockResolvedValue([{ id: 99, slug: "3d_printer", is_builtin: false, makerspace: 7 }, { id: 3, slug: "3d_printer", is_builtin: true, makerspace: null, name: "3D printer" }]);
  staffRequest.mockResolvedValue([{ id: 1, title: "Gear", status: "pending" }]);
  mount("pending_prints");
  expect(await screen.findByText("Gear · pending")).toBeVisible();
  expect(staffRequest).toHaveBeenCalledWith("/admin/makerspaces/7/machine-service/requests?status=pending&machine_type_id=3");
});
it("uses the paginated, server-scoped overdue list and links to its machine's maintenance tab", async () => {
  staffRequest.mockResolvedValue({ count: 30, results: [{ id: 5, machine_id: 9, machine_name: "Laser", description: "Clean optics", next_due: "2026-10-01" }] });
  mount("maintenance_overdue");
  expect(await screen.findByRole("link", { name: "Laser: Clean optics" })).toHaveAttribute("href", "/m/forge/admin/machines?machine=9&detail_tab=Maintenance");
  expect(staffRequest).toHaveBeenCalledWith("/admin/makerspace/7/maintenance-overdue?page=2");
  expect(getMachineTypes).not.toHaveBeenCalled();
});
it("makes no module-off queue requests", async () => {
  mount("pending_prints", false);
  expect(await screen.findByRole("alert")).toHaveTextContent("module is disabled");
  await waitFor(() => expect(staffRequest).not.toHaveBeenCalled()); expect(getMachineTypes).not.toHaveBeenCalled();
});
it("hides an already-cached maintenance list when its module becomes disabled", () => {
  const client = new QueryClient();
  client.setQueryData(["dashboard-maintenance-queue", 7, 1], { count: 1, results: [{ id: 5, machine_id: 9, machine_name: "Private laser", description: "Clean optics", next_due: "2026-10-01" }] });
  render(<QueryClientProvider client={client}><MemoryRouter initialEntries={["/admin/machines?work_queue=maintenance_overdue"]}>
    <DashboardMachineQueue makerspaceId={7} single guest={false} enabled={false} />
  </MemoryRouter></QueryClientProvider>);
  expect(screen.getByRole("alert")).toHaveTextContent("module is disabled");
  expect(screen.queryByText(/Private laser/)).not.toBeInTheDocument();
  expect(staffRequest).not.toHaveBeenCalled();
});
