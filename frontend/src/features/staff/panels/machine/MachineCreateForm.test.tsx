import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { MachineType } from "../../machinesApi";
import { MachineCreateForm } from "./MachineCreateForm";

const { staffRequest } = vi.hoisted(() => ({ staffRequest: vi.fn() }));

vi.mock("../../../../lib/api", () => ({ staffRequest }));
vi.mock("../../ImageUploader", () => ({
  ImageUploader: ({ endpoint, label }: { endpoint: string; label: string }) => (
    <div data-testid="image-uploader" data-endpoint={endpoint}>{label}</div>
  ),
}));

const printerType: MachineType = {
  id: 7,
  slug: "3d_printer",
  name: "3D printer",
  icon: "",
  is_builtin: true,
  managing_action: "manage_printing",
  makerspace: null,
};

function renderForm(onCreated = vi.fn()) {
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MachineCreateForm makerspaceId={3} machineType={printerType} onCreated={onCreated} />
    </QueryClientProvider>,
  );
  return onCreated;
}

function createdMachine(name = "Workshop printer") {
  return { id: 41, name, image_url: null };
}

describe("MachineCreateForm", () => {
  beforeEach(() => staffRequest.mockReset());

  it("creates a built-in printer with its make/model payload and location", async () => {
    staffRequest.mockResolvedValue(createdMachine());
    const onCreated = renderForm();

    fireEvent.change(screen.getByLabelText("Name"), { target: { value: " Workshop printer " } });
    fireEvent.change(screen.getByLabelText("Make and model"), { target: { value: " Prusa MK4 " } });
    fireEvent.change(screen.getByLabelText("Location"), { target: { value: " Fab lab " } });
    fireEvent.click(screen.getByRole("button", { name: "Add 3D printer" }));

    await waitFor(() => expect(onCreated).toHaveBeenCalledWith(41));
    expect(staffRequest).toHaveBeenCalledWith("/admin/makerspace/3/machines", {
      method: "POST",
      body: JSON.stringify({
        name: "Workshop printer",
        machine_type_id: 7,
        location: "Fab lab",
        notes: "",
        firmware_version: "",
        camera_feed_url: "",
        type_payload: { model: "Prusa MK4" },
      }),
    });
  });

  it("shows photo and warranty extras only after the machine is created", async () => {
    let resolveCreate: ((machine: ReturnType<typeof createdMachine>) => void) | undefined;
    staffRequest.mockReturnValue(new Promise((resolve) => { resolveCreate = resolve; }));
    renderForm();

    expect(screen.queryByTestId("image-uploader")).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Warranty" })).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Workshop printer" } });
    fireEvent.click(screen.getByRole("button", { name: "Add 3D printer" }));
    expect(screen.queryByTestId("image-uploader")).not.toBeInTheDocument();

    resolveCreate?.(createdMachine());

    const confirmation = await screen.findByText(/Workshop printer was created/);
    expect(confirmation).toHaveFocus();
    expect(screen.getByTestId("image-uploader")).toHaveAttribute("data-endpoint", "/admin/machines/41/image");
    expect(screen.getByRole("heading", { name: "Warranty" })).toBeVisible();
  });

  it("keeps creation success clear when optional warranty saving fails", async () => {
    staffRequest.mockImplementation(async (path?: string) => {
      if (path?.endsWith("/warranty")) throw new Error("Warranty service unavailable");
      return createdMachine("Reliable printer");
    });
    renderForm();

    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Reliable printer" } });
    fireEvent.click(screen.getByRole("button", { name: "Add 3D printer" }));
    await screen.findByText(/Reliable printer was created/);
    fireEvent.change(screen.getByLabelText("Vendor name"), { target: { value: "Printer Co" } });
    fireEvent.click(screen.getByRole("button", { name: "Save warranty" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Reliable printer is still created. Warranty details were not saved: Warranty service unavailable",
    );
    expect(staffRequest).toHaveBeenCalledWith("/admin/machines/41/warranty", {
      method: "PUT",
      body: JSON.stringify({ vendor_name: "Printer Co" }),
    });
    expect(screen.getByText(/Reliable printer was created/)).toBeVisible();
  });
});
