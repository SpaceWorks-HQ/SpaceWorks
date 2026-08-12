import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { MachineType } from "../../machinesApi";
import { MachineServiceConsole } from "./MachineServiceConsole";
import { blankServiceDraft } from "./serviceDrafts";

const { staffRequest } = vi.hoisted(() => ({ staffRequest: vi.fn() }));

vi.mock("../../../../lib/api", () => ({ staffRequest }));

describe("MachineServiceConsole", () => {
  it("uses its fixed machine type without rendering a type selector", async () => {
    const machineType: MachineType = {
      id: 7,
      slug: "laser",
      name: "Laser cutters",
      icon: "",
      is_builtin: false,
      managing_action: "manage_machines",
      makerspace: 1,
      capability_config: { metering_unit: "length", requires_booking: false },
    };
    staffRequest.mockImplementation(async (path?: string) => {
      if (path?.includes("machine-service/requests")) return [{ id: 4, title: "Laser job", status: "pending", planned_quantity: "20", actual_consumed_quantity: "0" }];
      return [];
    });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });

    render(
      <QueryClientProvider client={client}>
        <MachineServiceConsole makerspaceId={1} canManage machineType={machineType} machines={[]} pools={[]} draft={blankServiceDraft()} setDraft={vi.fn()} />
      </QueryClientProvider>,
    );

    expect(await screen.findByText("Laser job")).toBeVisible();
    expect(screen.queryByLabelText("Machine type")).not.toBeInTheDocument();
    await waitFor(() => expect(staffRequest.mock.calls.some(([path]) => String(path).includes("machine_type_id=7"))).toBe(true));
    expect(staffRequest.mock.calls.some(([path]) => String(path).includes("machine-types"))).toBe(false);
  });
});
