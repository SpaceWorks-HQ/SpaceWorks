import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { PrinterPool } from "../../../../generated/api";
import type { MachineType } from "../../machinesApi";
import { ConsumablePoolCreateForm } from "./ConsumablePoolCreateForm";

const { staffRequest } = vi.hoisted(() => ({ staffRequest: vi.fn() }));

vi.mock("../../../../lib/api", () => ({ staffRequest }));

const printerType: MachineType = {
  id: 2,
  slug: "3d_printer",
  name: "3D printers",
  icon: "",
  is_builtin: true,
  managing_action: "manage_printing",
  makerspace: null,
  capability_config: {
    metering_unit: "weight",
    requires_booking: false,
    accepted_materials: ["PLA", "PETG"],
    accepted_colours: ["Blue", "Signal red"],
  },
};

const existingPool = {
  id: 1,
  machine_id: null,
  machine_type_id: null,
  material: "PLA",
  color: "Blue",
  color_hex: "#123456",
  brand: "Prusament",
  initial_grams: "100",
  remaining_grams: "50",
  is_active: true,
  created_at: "2026-08-14T10:00:00Z",
  updated_at: "2026-08-14T10:00:00Z",
} satisfies PrinterPool;

let canConfigure = false;

function authUser() {
  return {
    username: "operator",
    email_verified: true,
    role: "staff",
    is_superuser: false,
    must_change_password: false,
    makerspaces: [{ id: 1, can_configure_machine_types: canConfigure }],
  };
}

function renderForm(machineType?: MachineType, pools: PrinterPool[] = [existingPool]) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ConsumablePoolCreateForm makerspaceId={1} machineType={machineType} existingPools={pools} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  canConfigure = false;
  staffRequest.mockReset();
  staffRequest.mockImplementation((path: string) => Promise.resolve(path === "/auth/me" ? authUser() : {}));
});

describe("ConsumablePoolCreateForm", () => {
  it("selects a named tile and submits its most recent pool hex separately", async () => {
    const { container } = renderForm(printerType);

    expect(screen.getByRole("combobox", { name: "Material" })).toHaveTextContent("PETG");
    expect(screen.getByRole("button", { name: "Signal red" })).toBeVisible();
    const brand = screen.getByRole("combobox", { name: "Brand" });
    const brandList = container.ownerDocument.getElementById(brand.getAttribute("list") ?? "");
    expect(brandList?.querySelector('option[value="Prusament"]')).not.toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Blue" }));
    expect(screen.getByRole("button", { name: "Blue" })).toHaveAttribute("aria-pressed", "true");
    fireEvent.change(screen.getByRole("combobox", { name: "Material" }), { target: { value: "PETG" } });
    fireEvent.change(brand, { target: { value: "Prusament" } });
    fireEvent.change(screen.getByRole("spinbutton", { name: "Initial quantity" }), { target: { value: "250" } });
    fireEvent.click(screen.getByRole("button", { name: "Add filament" }));

    await waitFor(() => {
      const call = staffRequest.mock.calls.find(([, options]) => options?.method === "POST");
      expect(call?.[0]).toBe("/admin/makerspaces/1/machine-service/consumable-pools");
      expect(JSON.parse(call?.[1]?.body as string)).toMatchObject({ color: "Blue", color_hex: "#123456" });
    });
  });

  it("appends a custom colour to accepted_colours and selects its name and hex", async () => {
    canConfigure = true;
    renderForm(printerType);

    fireEvent.click(await screen.findByRole("button", { name: "Add a custom colour" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Custom colour name" }), { target: { value: "Ocean teal" } });
    fireEvent.change(screen.getByLabelText("Colour picker"), { target: { value: "#147d80" } });
    fireEvent.click(screen.getByRole("button", { name: "Save custom colour" }));

    await waitFor(() => {
      const call = staffRequest.mock.calls.find(([, options]) => options?.method === "PATCH");
      expect(call?.[0]).toBe("/admin/makerspace/1/machine-types/2");
      expect(JSON.parse(call?.[1]?.body as string)).toMatchObject({
        name: "3D printers",
        icon: "",
        capability_config: {
          metering_unit: "weight",
          requires_booking: false,
          accepted_materials: ["PLA", "PETG"],
          accepted_colours: ["Blue", "Signal red", "Ocean teal"],
        },
      });
    });
    expect(await screen.findByRole("button", { name: "Ocean teal" })).toHaveAttribute("aria-pressed", "true");
  });

  it("refuses a case-insensitive duplicate custom colour before sending", async () => {
    canConfigure = true;
    renderForm(printerType);

    fireEvent.click(await screen.findByRole("button", { name: "Add a custom colour" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Custom colour name" }), { target: { value: " blue " } });
    fireEvent.click(screen.getByRole("button", { name: "Save custom colour" }));

    expect(screen.getByRole("alert")).toHaveTextContent("Colour name already exists.");
    expect(staffRequest.mock.calls.some(([, options]) => options?.method === "PATCH")).toBe(false);
  });

  it("hides custom colour configuration without machine-type configure permission", async () => {
    renderForm(printerType);

    await waitFor(() => expect(staffRequest).toHaveBeenCalledWith("/auth/me"));
    expect(screen.queryByRole("button", { name: "Add a custom colour" })).not.toBeInTheDocument();
  });

  it("keeps generic machine types on free-text fields with an optional swatch picker", () => {
    renderForm({
      ...printerType,
      id: 3,
      slug: "laser",
      name: "Laser cutter",
      is_builtin: false,
      makerspace: 1,
      capability_config: { metering_unit: "length", requires_booking: false },
    });

    expect(screen.getByRole("textbox", { name: "Material" })).toBeVisible();
    expect(screen.getByRole("textbox", { name: "Colour" })).toBeVisible();
    expect(screen.getByLabelText("Colour picker")).toBeVisible();
    expect(screen.getByRole("slider", { name: "red channel" })).toBeVisible();
  });
});
