import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { staffRequest } from "../../lib/api";
import { MembershipWaiverPanel } from "./MembershipWaiverPanel";
vi.mock("../../lib/api", () => ({ staffRequest: vi.fn() }));
function show() { render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><MembershipWaiverPanel makerspaceId={3} /></QueryClientProvider>); }
describe("MembershipWaiverPanel", () => {
  beforeEach(() => { vi.mocked(staffRequest).mockReset(); });
  it("loads the current waiver, publishes a new version and deactivates it", async () => {
    vi.mocked(staffRequest).mockResolvedValue({ has_waiver: true, version: "v1", body: "Be careful" }); show();
    expect(await screen.findByLabelText("Waiver text")).toHaveValue("Be careful");
    expect(screen.getByText("Publish waiver")).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Waiver version"), { target: { value: "v2" } }); fireEvent.click(screen.getByText("Publish waiver"));
    await waitFor(() => expect(staffRequest).toHaveBeenCalledWith("/admin/makerspaces/3/waiver", { method: "PUT", body: JSON.stringify({ version: "v2", body: "Be careful" }) }));
    await waitFor(() => expect(screen.getByText("Deactivate waiver")).toBeEnabled()); fireEvent.click(screen.getByText("Deactivate waiver"));
    await waitFor(() => expect(staffRequest).toHaveBeenCalledWith("/admin/makerspaces/3/waiver", { method: "PUT", body: JSON.stringify({ clear: true }) }));
  });
  it("explains when no waiver is active", async () => { vi.mocked(staffRequest).mockResolvedValue({ has_waiver: false }); show(); expect(await screen.findByText("No active waiver.")).toBeVisible(); });
  it("shows loading and errors", async () => { vi.mocked(staffRequest).mockRejectedValue(new Error("Waiver unavailable")); show(); expect(screen.getByText("Loading current waiver…")).toBeVisible(); expect(await screen.findByRole("alert")).toHaveTextContent("Waiver unavailable"); });
});
