import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { MachineTypesPanel } from "./MachineTypesPanel";

const { staffRequest } = vi.hoisted(() => ({ staffRequest: vi.fn() }));

vi.mock("../../../lib/api", () => ({ staffRequest }));

const customType = {
  id: 4,
  slug: "laser-cutter",
  name: "Laser cutter",
  icon: "",
  is_builtin: false,
  managing_action: "",
  makerspace: 7,
  capability_config: {
    metering_unit: "count",
    requires_booking: false,
    accepted_materials: ["Plywood"],
    accepted_colours: ["Clear"],
  },
};

function renderPanel(canConfigure = true) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MachineTypesPanel makerspaceId={7} canConfigureMachineTypes={canConfigure} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  staffRequest.mockReset();
  staffRequest.mockImplementation((path: string) => {
    if (path.endsWith("machine-type-pricing")) return Promise.resolve({ currency: "INR", results: [] });
    if (path.endsWith("machine-types")) return Promise.resolve([customType]);
    return Promise.resolve(customType);
  });
});

describe("MachineTypesPanel capability presets", () => {
  it("rejects blank and case-insensitive duplicate entries before creation", async () => {
    renderPanel();
    fireEvent.click(screen.getByText("Machine types and pricing"));
    const createButton = await screen.findByRole("button", { name: "Create type" });
    const createForm = createButton.closest("form");
    expect(createForm).not.toBeNull();
    const form = within(createForm!);

    fireEvent.click(form.getByRole("button", { name: "Add material" }));
    expect(form.getByRole("alert")).toHaveTextContent("Material cannot be blank.");

    fireEvent.change(form.getByRole("textbox", { name: "New material" }), { target: { value: "Acrylic" } });
    fireEvent.click(form.getByRole("button", { name: "Add material" }));
    fireEvent.change(form.getByRole("textbox", { name: "New material" }), { target: { value: "acrylic" } });
    fireEvent.click(form.getByRole("button", { name: "Add material" }));

    expect(form.getByRole("alert")).toHaveTextContent("Material already exists.");
    expect(form.getByRole("button", { name: "Remove material Acrylic" })).toBeVisible();
  });

  it("omits a preset key when the custom type list is emptied", async () => {
    renderPanel();
    fireEvent.click(screen.getByText("Machine types and pricing"));
    const saveButton = await screen.findByRole("button", { name: "Save type" });
    const editForm = saveButton.closest("form");
    expect(editForm).not.toBeNull();
    const form = within(editForm!);

    fireEvent.click(form.getByRole("button", { name: "Remove material Plywood" }));
    fireEvent.click(saveButton);

    await waitFor(() => {
      const updateCall = staffRequest.mock.calls.find(([, options]) => options?.method === "PATCH");
      expect(updateCall).toBeDefined();
      const body = JSON.parse(updateCall![1].body);
      expect(body.capability_config).not.toHaveProperty("accepted_materials");
      expect(body.capability_config.accepted_colours).toEqual(["Clear"]);
    });
  });
});
