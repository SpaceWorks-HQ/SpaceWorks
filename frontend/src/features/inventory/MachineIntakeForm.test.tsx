import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MachineIntakeForm } from "./MachineIntakeForm";
import { tenantPublicRequest } from "../../lib/api";

vi.mock("../../lib/api", () => ({ tenantPublicRequest: vi.fn() }));
const request = vi.mocked(tenantPublicRequest);
function view() {
  return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <MachineIntakeForm slug="lab" machineId={7} typeId={4} />
  </QueryClientProvider>);
}

describe("structured machine intake", () => {
  beforeEach(() => { request.mockReset(); });
  it("sends versioned typed fields, with blank optional numbers omitted", async () => {
    request.mockResolvedValueOnce({ materials: [], intake_schema: { version: 1, fields: [
      { key: "thickness", label: "Thickness", type: "number", required: true },
      { key: "length", label: "Length", type: "number" },
      { key: "finish", label: "Finish", type: "boolean", required: true },
    ] } }).mockResolvedValueOnce({ status: "pending" });
    view();
    fireEvent.change(await screen.findByLabelText("Thickness"), { target: { value: "2.5" } });
    fireEvent.change(screen.getByLabelText("Job title"), { target: { value: "Cut panel" } });
    fireEvent.change(screen.getByLabelText("Length"), { target: { value: "10" } });
    fireEvent.change(screen.getByLabelText("Length"), { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: "Request work" }));
    await screen.findByText("Request submitted for review.");
    const body = request.mock.calls[1][2]?.body;
    expect(JSON.parse(String(body))).toEqual({ machine_id: 7, title: "Cut panel", capability_payload: {
      schema_version: 1, values: { thickness: 2.5, finish: false },
    } });
  });
  it("does not render a generic job form for an absent schema", async () => {
    request.mockResolvedValue({ materials: [], intake_schema: {} });
    view();
    await waitFor(() => expect(screen.queryByRole("button", { name: "Request work" })).not.toBeInTheDocument());
    expect(screen.queryByLabelText("Job title")).not.toBeInTheDocument();
  });
});
