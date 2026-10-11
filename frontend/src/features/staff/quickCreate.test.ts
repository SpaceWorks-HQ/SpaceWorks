import { describe, expect, it } from "vitest";
import { quickCreateCommands } from "./quickCreate";
describe("palette quick-create", () => {
  it("requires both the action and an enabled tab", () => {
    expect(quickCreateCommands(["view_inventory"], ["inventory"])).toEqual([]);
    expect(quickCreateCommands(["manage_events"], ["inventory"])).toEqual([]);
    expect(quickCreateCommands(["edit_inventory", "manage_events"], ["inventory", "events"]).map(row => row.label)).toEqual(["New item", "New event"]);
  });
  it("allows a superadmin only within module-filtered tabs and carries the creation intent", () => {
    const commands = quickCreateCommands([], ["bookings"], true);
    expect(commands).toHaveLength(1); expect(commands[0].query).toEqual({ create: "booking" });
  });
});
