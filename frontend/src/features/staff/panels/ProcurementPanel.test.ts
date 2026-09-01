import { describe, expect, it } from "vitest";

import { groupProcurementRows, type ToBuyItem } from "./ProcurementPanelRows";
import {
  procurementMachineTypeOptions,
  procurementMachineTypeRequired,
} from "./ProcurementPanelTypes";

function item(
  id: number,
  machineType: number | null,
  machineTypeName: string | null,
): ToBuyItem {
  return {
    id,
    kind: "printing",
    machine_type: machineType,
    machine_type_name: machineTypeName,
    name: `Item ${id}`,
    quantity: 1,
    link: "",
    status: "requested",
    estimated_unit_cost: null,
    vendor_name: "",
    actual_unit_cost: null,
    purchaser_username: null,
    ordered_at: null,
    received_at: null,
    moved_to_inventory_at: null,
    resulting_product: null,
    resulting_pool: null,
    resulting_machine: null,
    source_pool: null,
    created_by_username: null,
    receipts: [],
  };
}

describe("procurement machine-type presentation", () => {
  it("groups typed rows by heading and emits Unassigned only when NULL rows exist", () => {
    const grouped = groupProcurementRows([
      item(1, 2, "Printers"),
      item(2, null, null),
      item(3, 1, "Lasers"),
      item(4, 1, "Lasers"),
    ]);

    expect(grouped.map((group) => [group.label, group.rows.map((row) => row.id)])).toEqual([
      ["Lasers", [3, 4]],
      ["Printers", [1]],
      ["Unassigned", [2]],
    ]);
    expect(groupProcurementRows([item(1, 1, "Lasers")]).map((group) => group.label))
      .not.toContain("Unassigned");
  });

  it("uses only the server-scoped machine type options", () => {
    const reachable = { id: 1, name: "Lasers" };

    expect(
      procurementMachineTypeOptions({
        machine_type_required: true,
        results: [reachable],
      }),
    ).toEqual([reachable]);
    expect(procurementMachineTypeOptions(undefined)).toEqual([]);
  });

  it("takes the requirement from the server and never demands one while loading", () => {
    // Defaulting to `true` before the payload arrives would block the form with a
    // required field whose satisfying options have not loaded yet.
    expect(procurementMachineTypeRequired(undefined)).toBe(false);
    expect(
      procurementMachineTypeRequired({ machine_type_required: true, results: [] }),
    ).toBe(true);
    expect(
      procurementMachineTypeRequired({
        machine_type_required: false,
        results: [{ id: 1, name: "Lasers" }],
      }),
    ).toBe(false);
  });
});
