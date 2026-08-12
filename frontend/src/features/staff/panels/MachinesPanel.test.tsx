import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { PrinterPool } from "../../../generated/api";
import type { Machine, MachineStatus, MachineType } from "../machinesApi";
import { MachinesPanel } from "./MachinesPanel";

const { staffRequest } = vi.hoisted(() => ({ staffRequest: vi.fn() }));

vi.mock("../../../lib/api", () => ({ staffRequest }));
vi.mock("./MachineTypesPanel", () => ({ MachineTypesPanel: () => null }));
vi.mock("./machine/MachineDrawer", () => ({ MachineDrawer: () => null }));

const laserType: MachineType = {
  id: 1, slug: "laser", name: "Laser cutters", icon: "✦", is_builtin: false,
  managing_action: "manage_machines", makerspace: 1, can_create_machine: true,
  capability_config: { metering_unit: "length", requires_booking: false },
};
const printerType: MachineType = {
  id: 2, slug: "3d_printer", name: "3D printers", icon: "", is_builtin: true,
  managing_action: "manage_printing", makerspace: null, can_create_machine: false,
  capability_config: { metering_unit: "weight", requires_booking: false },
};

function machine(id: number, name: string, type = laserType, status: MachineStatus = "idle"): Machine {
  return {
    id, makerspace: 1, machine_type: type, name, location: "Lab", notes: "", status,
    firmware_version: "", camera_feed_url: "", image_url: null, warranty_status: "unknown",
    is_public: true, is_active: true, usage_hours: "0", can_operate: true, can_edit: true,
    can_delegate: true, can_retire: true, can_unretire: false, can_manage: true,
    created_at: "", updated_at: "",
  };
}

function pool(id: number, material: string, machineId: number | null, unit: PrinterPool["unit"] = "millimeters"): PrinterPool {
  return {
    id, machine_id: machineId, material, color: "", brand: "", unit,
    initial_grams: "100", remaining_grams: "80", is_active: true, created_at: "", updated_at: "",
  };
}

type Setup = {
  types?: MachineType[];
  machines?: Machine[];
  pools?: PrinterPool[];
  requests?: Record<string, unknown[]>;
};

function renderPanel(setup: Setup = {}, props: Partial<React.ComponentProps<typeof MachinesPanel>> = {}) {
  const types = setup.types ?? [laserType];
  const rows = setup.machines ?? [];
  const pools = setup.pools ?? [];
  const requests = setup.requests ?? {};
  staffRequest.mockImplementation(async (path: string) => {
    if (!path) return [];
    if (path.endsWith("/machine-types")) return types;
    if (path.endsWith("/machines")) return { count: rows.length, results: rows };
    if (path.includes("machine-service-report")) return { printer_metrics: [] };
    if (path.includes("machine-service/requests")) {
      // The consoles now filter by the stable machine-type ID (a slug is not unique across
      // the global/tenant split), so resolve it back to the slug the fixtures are keyed by.
      const params = new URLSearchParams(path.split("?")[1]);
      const typeId = Number(params.get("machine_type_id"));
      const slug = types.find((type) => type.id === typeId)?.slug
        ?? params.get("machine_type")
        ?? "";
      return requests[slug] ?? [];
    }
    if (path.includes("typed-manual-usage")) return [];
    if (path.endsWith("machine-service/consumable-pools")) return pools;
    return [];
  });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MachinesPanel makerspaceId={1} canManage canConfigureMachineTypes={false} maintenanceEnabled={false} machineServiceEnabled printingEnabled {...props} />
    </QueryClientProvider>,
  );
}

beforeEach(() => staffRequest.mockReset());

describe("MachinesPanel type sections", () => {
  it("renders a zero-machine reachable type and its service queue", async () => {
    renderPanel({ requests: { laser: [{ id: 10, title: "Cut acrylic", status: "pending", planned_quantity: "20", actual_consumed_quantity: "0" }] } });

    expect(await screen.findByText("No machines are registered for this type.")).toBeVisible();
    expect(await screen.findByText("Cut acrylic")).toBeVisible();
  });

  it("keeps service content mounted when the status filter removes every row", async () => {
    renderPanel({ machines: [machine(1, "Laser One")], requests: { laser: [{ id: 10, title: "Cut acrylic", status: "pending", planned_quantity: "20", actual_consumed_quantity: "0" }] } });
    expect(await screen.findByText("Cut acrylic")).toBeVisible();

    fireEvent.change(screen.getByLabelText("Status"), { target: { value: "offline" } });

    expect(screen.getByText("No machines match the selected status.")).toBeVisible();
    expect(screen.getByText("Cut acrylic")).toBeVisible();
  });

  it("shows shared pools only in the Shared consumables section", async () => {
    renderPanel({ pools: [pool(1, "Shared acrylic", null)] });
    await screen.findByRole("button", { name: /Laser cutters.*0 items/ });
    expect(screen.queryByText(/Shared acrylic/, { selector: "span" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Shared consumables.*1 item\b/ }));

    expect(screen.getAllByText(/Shared acrylic/, { selector: "span" })).toHaveLength(1);
  });

  it("shows a bound pool only under its machine's type", async () => {
    const printer = machine(2, "Printer One", printerType);
    renderPanel({ types: [laserType, printerType], machines: [machine(1, "Laser One"), printer], pools: [pool(2, "Printer PLA", 2, "grams")] });
    await screen.findByRole("button", { name: /Laser One/ });
    expect(screen.queryByText(/Printer PLA/, { selector: "span" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /3D printers.*1 item\b/ }));

    expect(screen.getAllByText(/Printer PLA/, { selector: "span" })).toHaveLength(1);
  });

  it("offers shared pools plus only the selected machine's bound pool", async () => {
    const rows = [machine(1, "Laser One"), machine(2, "Laser Two")];
    const pools = [pool(1, "Shared acrylic", null), pool(2, "One acrylic", 1), pool(3, "Two acrylic", 2)];
    renderPanel({ machines: rows, pools, requests: { laser: [{ id: 10, title: "Cut acrylic", status: "accepted", planned_quantity: "20", actual_consumed_quantity: "0" }] } });
    fireEvent.click(await screen.findByRole("button", { name: "Start" }));
    fireEvent.change(screen.getByLabelText("Machine"), { target: { value: "1" } });

    const startPool = screen.getByLabelText("Pool");
    expect(within(startPool).getByRole("option", { name: /Shared acrylic/ })).toBeInTheDocument();
    expect(within(startPool).getByRole("option", { name: /One acrylic/ })).toBeInTheDocument();
    expect(within(startPool).queryByRole("option", { name: /Two acrylic/ })).not.toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Manual usage machine"), { target: { value: "2" } });
    const manualPool = screen.getByLabelText("Manual usage pool");
    expect(within(manualPool).getByRole("option", { name: /Shared acrylic/ })).toBeInTheDocument();
    expect(within(manualPool).getByRole("option", { name: /Two acrylic/ })).toBeInTheDocument();
    expect(within(manualPool).queryByRole("option", { name: /One acrylic/ })).not.toBeInTheDocument();
  });

  it("limits machine creation to explicitly authorized types", async () => {
    renderPanel({ types: [laserType, printerType] });
    const selector = await screen.findByLabelText("Machine type");

    expect(within(selector).getByRole("option", { name: "Laser cutters" })).toBeInTheDocument();
    expect(within(selector).queryByRole("option", { name: "3D printers" })).not.toBeInTheDocument();
  });

  it("hides machine creation when no type grants creation authority", async () => {
    renderPanel({ types: [{ ...laserType, can_create_machine: false }, { ...printerType, can_create_machine: undefined }] });
    await screen.findByRole("button", { name: /Laser cutters/ });

    expect(screen.queryByLabelText("Machine type")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "New machine" })).not.toBeInTheDocument();
  });

  it("mounts no service requests when machine_service is disabled", async () => {
    renderPanel({ types: [printerType, laserType] }, { machineServiceEnabled: false });
    await screen.findByRole("button", { name: /3D printers/ });

    await waitFor(() => expect(staffRequest.mock.calls.filter(([path]) => path)).toHaveLength(2));
    const paths = staffRequest.mock.calls.map(([path]) => String(path));
    expect(paths.filter((path) => path.includes("machine-service"))).toEqual([]);
    expect(paths.filter((path) => path.includes("typed-manual-usage"))).toEqual([]);
    expect(paths.filter((path) => path.includes("machine-service-report"))).toEqual([]);
  });

  it("fetches pools once and service data only for the initially open type", async () => {
    renderPanel({ types: [laserType, printerType] });
    await screen.findByText("Service queue");
    await waitFor(() => expect(staffRequest.mock.calls.some(([path]) => String(path).includes("typed-manual-usage"))).toBe(true));
    const paths = staffRequest.mock.calls.map(([path]) => String(path));

    expect(paths.filter((path) => path.endsWith("machine-service/consumable-pools"))).toHaveLength(1);
    expect(paths.filter((path) => path.includes("machine-service/requests"))).toHaveLength(1);
    expect(paths.some((path) => path.includes(`machine_type_id=${printerType.id}`))).toBe(false);
    expect(paths.some((path) => path.includes("machine-service-report"))).toBe(false);
  });

  it("preserves a service action draft across collapse and reopen", async () => {
    renderPanel({ requests: { laser: [{ id: 10, title: "Cut acrylic", status: "in_progress", planned_quantity: "20", actual_consumed_quantity: "0" }] } });
    fireEvent.click(await screen.findByRole("button", { name: "Complete" }));
    const actualMinutes = screen.getByLabelText("Actual minutes");
    fireEvent.change(actualMinutes, { target: { value: "37" } });
    const sectionButton = screen.getByRole("button", { name: /Laser cutters.*0 items/ });

    fireEvent.click(sectionButton);
    expect(screen.queryByLabelText("Actual minutes")).not.toBeInTheDocument();
    fireEvent.click(sectionButton);

    expect(screen.getByLabelText("Actual minutes")).toHaveValue("37");
  });

  // A makerspace may legally create a LOCAL type slugged `3d_printer`. Backend printer
  // semantics require the GLOBAL type (`printer_capabilities.is_printer_type`), so matching
  // the slug alone mounts the printer console for a generic service and makes two sections
  // query the same slug, duplicating and mixing their jobs.
  it("does not treat a makerspace-local type slugged 3d_printer as the built-in printer", async () => {
    const impostor: MachineType = { ...printerType, id: 3, makerspace: 1, name: "Shop printers", is_builtin: false };
    renderPanel({ types: [impostor], machines: [machine(1, "Shop A", impostor)] });

    // Wait for the generic console to actually mount before asserting on absence -- checking
    // network calls straight after the heading appears races the console's own queries, and
    // passes even when the printer console IS wrongly mounted.
    expect(await screen.findByText("Service queue")).toBeVisible();
    expect(screen.queryByText("3D-printer queue")).not.toBeInTheDocument();
    expect(screen.queryByText("Printer reports")).not.toBeInTheDocument();
  });

  // The machine and machine-type requests are independent. If the type response omits a type
  // whose machines loaded fine, those machines must still appear -- the grouping this replaced
  // appended unknown types rather than dropping them.
  it("still renders machines whose type is missing from the machine-type response", async () => {
    renderPanel({ types: [], machines: [machine(1, "Orphaned laser")] });

    await screen.findByRole("button", { name: /Laser cutters/ });
    // `strong` is the machine row; the name also appears in a service form's machine selector.
    expect(screen.getByText("Orphaned laser", { selector: "strong" })).toBeInTheDocument();
  });
});
