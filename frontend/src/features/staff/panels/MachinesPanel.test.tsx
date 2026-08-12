import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
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
  /** Extra pages keyed by `?page=N`, for the paginated-fleet test. */
  machinePages?: Record<string, { count: number; next: string | null; results: Machine[] }>;
};

function mockApi(setup: Setup) {
  const types = setup.types ?? [laserType];
  const rows = setup.machines ?? [];
  const pools = setup.pools ?? [];
  const requests = setup.requests ?? {};
  staffRequest.mockImplementation(async (path: string) => {
    if (!path) return [];
    if (path.endsWith("/machine-types")) return types;
    if (path.includes("/machines?page=")) {
      const page = new URLSearchParams(path.split("?")[1]).get("page") ?? "";
      return setup.machinePages?.[page] ?? { count: rows.length, next: null, results: [] };
    }
    if (path.endsWith("/machines")) {
      return setup.machinePages?.["1"] ?? { count: rows.length, next: null, results: rows };
    }
    if (path.includes("machine-service-report")) return { printer_metrics: [] };
    if (path.includes("machine-service/requests")) {
      // The consoles filter by the stable machine-type ID (a slug is not unique across the
      // global/tenant split), so resolve it back to the slug the fixtures are keyed by.
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
}

function renderPanel(
  setup: Setup = {},
  props: Partial<React.ComponentProps<typeof MachinesPanel>> = {},
  route = "/admin/machines",
) {
  mockApi(setup);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  // A REAL router, not a location stub: the panel resolves its selected machine type from
  // the URL and navigates with `<Link>`/`<Navigate>`, and a stub that only fakes
  // `window.location` passes against code that never reads router context at all.
  return render(
    <MemoryRouter initialEntries={[route]}>
      <QueryClientProvider client={client}>
        <MachinesPanel makerspaceId={1} canManage canConfigureMachineTypes={false} maintenanceEnabled={false} machineServiceEnabled printingEnabled delegatedRecipientRulesEnabled={false} {...props} />
      </QueryClientProvider>
    </MemoryRouter>,
  );
}

beforeEach(() => staffRequest.mockReset());

describe("MachinesPanel index and per-type subpages", () => {
  it("shows delegated maintenance recipients only when the switch is enabled", async () => {
    renderPanel({}, { maintenanceEnabled: true });
    expect(screen.queryByRole("heading", { name: "Who gets notified" })).not.toBeInTheDocument();

    renderPanel({}, { maintenanceEnabled: true, delegatedRecipientRulesEnabled: true });

    expect(await screen.findByRole("heading", { name: "Who gets notified" })).toBeVisible();
  });

  // A single reachable type renders ITS PAGE inline at the index URL rather than redirecting.
  // An unconditional redirect would make the index unreachable, and with it machine creation,
  // machine-type configuration, shared pools and the delegated recipient picker -- all of
  // which the scoped maintainer with one type is exactly the actor who needs them.
  it("renders the sole reachable type inline without hiding the index controls", async () => {
    renderPanel({ types: [laserType] });

    expect(await screen.findByText("No machines are registered for this type.")).toBeVisible();
    expect(screen.getByLabelText("Machine type")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Shared consumables/ })).toBeInTheDocument();
  });

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
    await screen.findByText("No machines are registered for this type.");
    expect(screen.queryByText(/Shared acrylic/, { selector: "span" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Shared consumables.*1 item\b/ }));

    expect(screen.getAllByText(/Shared acrylic/, { selector: "span" })).toHaveLength(1);
  });

  it("shows a bound pool only on its machine's type page", async () => {
    const setup: Setup = {
      types: [laserType, printerType],
      machines: [machine(1, "Laser One"), machine(2, "Printer One", printerType)],
      pools: [pool(2, "Printer PLA", 2, "grams")],
    };
    renderPanel(setup, {}, "/admin/machines/1-laser");
    await screen.findByText("Laser One", { selector: "strong" });
    expect(screen.queryByText(/Printer PLA/, { selector: "span" })).not.toBeInTheDocument();

    renderPanel(setup, {}, "/admin/machines/2-3d_printer");

    expect(await screen.findByText("Printer One", { selector: "strong" })).toBeVisible();
    expect(screen.getAllByText(/Printer PLA/, { selector: "span" }).length).toBeGreaterThan(0);
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
    await screen.findByRole("link", { name: /Laser cutters/ });

    expect(screen.queryByLabelText("Machine type")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "New machine" })).not.toBeInTheDocument();
  });

  it("mounts no service requests when machine_service is disabled", async () => {
    renderPanel({ types: [printerType, laserType] }, { machineServiceEnabled: false });
    await screen.findByRole("link", { name: /3D printers/ });

    await waitFor(() => expect(staffRequest.mock.calls.filter(([path]) => path)).toHaveLength(2));
    const paths = staffRequest.mock.calls.map(([path]) => String(path));
    expect(paths.filter((path) => path.includes("machine-service"))).toEqual([]);
    expect(paths.filter((path) => path.includes("typed-manual-usage"))).toEqual([]);
    expect(paths.filter((path) => path.includes("machine-service-report"))).toEqual([]);
  });

  it("fetches pools once and service data only for the open type", async () => {
    renderPanel({ types: [laserType, printerType] }, {}, "/admin/machines/1-laser");
    await screen.findByText("Service queue");
    await waitFor(() => expect(staffRequest.mock.calls.some(([path]) => String(path).includes("typed-manual-usage"))).toBe(true));
    const paths = staffRequest.mock.calls.map(([path]) => String(path));

    expect(paths.filter((path) => path.endsWith("machine-service/consumable-pools"))).toHaveLength(1);
    expect(paths.filter((path) => path.includes("machine-service/requests"))).toHaveLength(1);
    expect(paths.some((path) => path.includes(`machine_type_id=${printerType.id}`))).toBe(false);
    expect(paths.some((path) => path.includes("machine-service-report"))).toBe(false);
  });

  // Drafts used to survive section COLLAPSE; with subpages the equivalent risk is
  // navigation. `useServiceDrafts` therefore lives in the container that stays mounted,
  // not in the type page which unmounts on every move.
  it("preserves a service action draft across navigation to the index and back", async () => {
    renderPanel(
      { types: [laserType, printerType], requests: { laser: [{ id: 10, title: "Cut acrylic", status: "in_progress", planned_quantity: "20", actual_consumed_quantity: "0" }] } },
      {},
      "/admin/machines/1-laser",
    );
    fireEvent.click(await screen.findByRole("button", { name: "Complete" }));
    fireEvent.change(screen.getByLabelText("Actual minutes"), { target: { value: "37" } });

    fireEvent.click(screen.getByRole("link", { name: /All machine types/ }));
    expect(screen.queryByLabelText("Actual minutes")).not.toBeInTheDocument();
    fireEvent.click(await screen.findByRole("link", { name: /Laser cutters/ }));

    expect(await screen.findByLabelText("Actual minutes")).toHaveValue("37");
  });

  // A makerspace may legally create a LOCAL type slugged `3d_printer`. Backend printer
  // semantics require the GLOBAL type (`printer_capabilities.is_printer_type`), so matching
  // the slug alone mounts the printer console for a generic service.
  it("does not treat a makerspace-local type slugged 3d_printer as the built-in printer", async () => {
    const impostor: MachineType = { ...printerType, id: 3, makerspace: 1, name: "Shop printers", is_builtin: false };
    renderPanel({ types: [impostor], machines: [machine(1, "Shop A", impostor)] });

    expect(await screen.findByText("Service queue")).toBeVisible();
    expect(screen.queryByText("3D-printer queue")).not.toBeInTheDocument();
    expect(screen.queryByText("Printer reports")).not.toBeInTheDocument();
  });

  // The machine and machine-type requests are independent. If the type response omits a type
  // whose machines loaded fine, those machines must still appear -- and the type must still be
  // navigable, because the machines list is server-scoped too.
  it("still renders machines whose type is missing from the machine-type response", async () => {
    renderPanel({ types: [], machines: [machine(1, "Orphaned laser")] });

    expect(await screen.findByText("Orphaned laser", { selector: "strong" })).toBeInTheDocument();
  });

  // THE ID IS AUTHORITATIVE, THE SLUG IS DECORATION. Slug uniqueness is only scoped, so a
  // makerspace-local type may carry a global built-in's slug; resolving by slug has already
  // served one type's jobs under another on three shipped surfaces.
  it("selects the machine type by id even when the slug in the URL names another type", async () => {
    renderPanel(
      { types: [laserType, printerType], machines: [machine(1, "Laser One")] },
      {},
      "/admin/machines/1-3d_printer",
    );

    expect(await screen.findByText("Laser One", { selector: "strong" })).toBeVisible();
    expect(screen.queryByText("Printer reports")).not.toBeInTheDocument();
  });

  it("normalises an unreachable machine type back to the index", async () => {
    renderPanel({ types: [laserType, printerType] }, {}, "/admin/machines/999-ghost");

    // The index, not a denial page: a stale deep link is a bad bookmark, not an attempt to
    // reach something forbidden.
    expect(await screen.findByRole("link", { name: /Laser cutters/ })).toBeVisible();
    expect(await screen.findByRole("link", { name: /3D printers/ })).toBeVisible();
  });

  // Counts and status roll-ups are stated as fact on the index cards, so the fleet has to be
  // read in full. The backend pages at 200; consuming only the first page would print a
  // wrong number rather than an obviously truncated list.
  it("counts machines across every page of the fleet", async () => {
    const first = [machine(1, "Laser One"), machine(2, "Laser Two")];
    const second = [machine(3, "Laser Three", laserType, "running")];
    renderPanel({
      types: [laserType, printerType],
      machinePages: {
        "1": { count: 3, next: "http://api.example/admin/makerspace/1/machines?page=2", results: first },
        "2": { count: 3, next: null, results: second },
      },
    });

    expect(await screen.findByText("3 machines")).toBeVisible();
    expect(screen.getByText("1 running")).toBeVisible();
  });
});
