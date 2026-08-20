import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ApiClientScopePicker } from "./ApiClientScopePicker";
import type { ApiClientScopeOption } from "./apiClientsApi";


const options: ApiClientScopeOption[] = [
  {
    value: "public:read",
    label: "Public read",
    description: "Read public routes.",
    group: "Public API",
    grantable: true,
    lock_reason: null,
  },
  {
    value: "legacy:v1",
    label: "Legacy v1 compatibility",
    description: "Frozen cutover access.",
    group: "Legacy",
    grantable: false,
    lock_reason: "Only a global superadmin may grant this scope.",
  },
];


describe("ApiClientScopePicker", () => {
  it("disables locked scopes and explains the lock", () => {
    render(
      <ApiClientScopePicker
        options={options}
        selected={["legacy:v1"]}
        onChange={vi.fn()}
      />,
    );

    expect(screen.getByRole("checkbox", { name: /legacy v1 compatibility/i })).toBeDisabled();
    expect(screen.getByText(/only a global superadmin/i)).toBeTruthy();
  });

  it("uses set-style selection without duplicates", () => {
    const onChange = vi.fn();
    render(
      <ApiClientScopePicker
        options={options}
        selected={[]}
        onChange={onChange}
      />,
    );

    fireEvent.click(screen.getByRole("checkbox", { name: /public read/i }));

    expect(onChange).toHaveBeenCalledWith(["public:read"]);
  });
});
