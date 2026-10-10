import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { staffRequest } from "../../lib/api";
import { BookableSpaceMachineType } from "./BookableSpaceMachineType";

vi.mock("../../lib/api", () => ({ staffRequest: vi.fn() }));

describe("bookable-space training link", () => {
  it("selects a scoped type by name and submits its authoritative id", async () => {
    vi.mocked(staffRequest).mockResolvedValue([{ id: 5, name: "Laser" }]);
    const change = vi.fn();
    render(<QueryClientProvider client={new QueryClient()}><BookableSpaceMachineType makerspaceId={2} value={null} onChange={change} /></QueryClientProvider>);
    expect(await screen.findByRole("option", { name: "Laser" })).toBeVisible();
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "5" } });
    expect(change).toHaveBeenCalledWith(5);
  });
  it("retains a configured link when type discovery is unavailable", async () => {
    vi.mocked(staffRequest).mockRejectedValue(new Error("Forbidden"));
    const change = vi.fn();
    render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><BookableSpaceMachineType makerspaceId={2} value={9} onChange={change} /></QueryClientProvider>);
    expect(await screen.findByText(/Machine types are unavailable/)).toBeVisible();
    expect(screen.getByRole("combobox")).toHaveValue("9");
    expect(change).not.toHaveBeenCalled();
  });
});
