import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { RoleEditor } from "./RoleEditor";
import type { Capability } from "./rolesApi";

const { createRole } = vi.hoisted(() => ({ createRole: vi.fn(async (_msId: number, _body: { name: string; granted_actions: string[] }) => ({})) }));
vi.mock("./rolesApi", () => ({ createRole, updateRole: vi.fn() }));
vi.mock("./RoleMachineScopeEditor", () => ({ RoleMachineScopeEditor: () => null }));

const handout = ["view_inventory", "assign_box", "issue_request", "issue_direct_loan", "return_request", "upload_evidence", "collect_service_request"];
const capabilities = ["manage_members", "view_finance", "record_payment", ...handout].map((value) => ({
  value, label: value, description: `Description for ${value}`, group: "Test", grantable: true,
})) as Capability[];

describe("custom role presets", () => {
  it.each([
    ["Membership Coordinator", ["manage_members"]],
    ["Treasurer", ["view_finance", "record_payment"]],
    ["Front-desk cashier", ["record_payment", ...handout]],
  ] as const)("prefills %s without creating it until Save", async (name, actions) => {
    createRole.mockClear();
    render(<QueryClientProvider client={new QueryClient()}>
      <RoleEditor msId={7} role={null} capabilities={capabilities} actorActions={["manage_makerspace"]} isSuperadmin={false} onClose={vi.fn()} onSaved={vi.fn()} />
    </QueryClientProvider>);
    fireEvent.click(screen.getByRole("button", { name }));
    expect(screen.getByRole("textbox")).toHaveValue(name);
    for (const capability of capabilities) {
      expect((screen.getByRole("checkbox", { name: new RegExp(capability.value) }) as HTMLInputElement).checked).toBe(actions.includes(capability.value as never));
    }
    expect(createRole).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Save role" }));
    await waitFor(() => expect(createRole).toHaveBeenCalledWith(7, { name, granted_actions: expect.arrayContaining([...actions]) }));
    expect(createRole.mock.calls[0][1].granted_actions).toHaveLength(actions.length);
  });
});
