import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { KitChecklistCapture, useKitChecklist } from "./KitChecklist";
import type { KitPreview } from "./KitChecklist";

const preview: KitPreview = { components: [{ key: "bits", label: "Bits", owner_label: "Driver kit", quantity: 12, issue_present: 11 }] };

function Harness({ target, submit, request }: { target: number; submit: (counts: { key: string; present: number }[]) => void;
  request: () => Promise<KitPreview> }) {
  const kits = useKitChecklist("/preview", { request_id: target, phase: "return" }, true, request);
  return <><KitChecklistCapture checklist={kits} /><button disabled={!kits.ready} onClick={() => submit(kits.counts)}>Return</button></>;
}

describe("kit physical count capture", () => {
  it("requires an explicit physical count and sends 0 for a missing component", async () => {
    const submit = vi.fn();
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={client}><Harness target={1} submit={submit} request={async () => preview} /></QueryClientProvider>);
    const input = await screen.findByRole("spinbutton", { name: /Driver kit: Bits/ });
    expect(screen.getByRole("button", { name: "Return" })).toBeDisabled();
    fireEvent.change(input, { target: { value: "13" } });
    expect(screen.getByRole("button", { name: "Return" })).toBeDisabled();
    fireEvent.change(input, { target: { value: "0" } });
    await waitFor(() => expect(screen.getByRole("button", { name: "Return" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Return" }));
    expect(submit).toHaveBeenCalledWith([{ key: "bits", present: 0 }]);
  });

  it("does not carry counts onto another loan even with identical component keys", async () => {
    const submit = vi.fn();
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const request = async () => preview;
    const { rerender } = render(<QueryClientProvider client={client}><Harness target={1} submit={submit} request={request} /></QueryClientProvider>);
    const input = await screen.findByRole("spinbutton");
    fireEvent.change(input, { target: { value: "12" } });
    await waitFor(() => expect(screen.getByRole("button", { name: "Return" })).toBeEnabled());
    rerender(<QueryClientProvider client={client}><Harness target={2} submit={submit} request={request} /></QueryClientProvider>);
    await waitFor(() => expect(screen.getByRole("spinbutton")).toHaveValue(null));
    expect(screen.getByRole("button", { name: "Return" })).toBeDisabled();
    rerender(<QueryClientProvider client={client}><Harness target={1} submit={submit} request={request} /></QueryClientProvider>);
    await waitFor(() => expect(screen.getByRole("spinbutton")).toHaveValue(null));
    expect(screen.getByRole("button", { name: "Return" })).toBeDisabled();
  });

  it("blocks submission when the required checklist cannot be loaded", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={client}><Harness target={1} submit={vi.fn()} request={async () => { throw new Error("Checklist unavailable"); }} /></QueryClientProvider>);
    expect(await screen.findByRole("alert")).toHaveTextContent("Checklist unavailable");
    expect(screen.getByRole("button", { name: "Return" })).toBeDisabled();
  });
});
