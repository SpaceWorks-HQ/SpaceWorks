import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { BillingDocumentsSettings } from "./BillingDocumentsSettings";

const { staffRequest } = vi.hoisted(() => ({ staffRequest: vi.fn() }));
vi.mock("../../lib/api", () => ({ staffRequest }));
const policy = { number_prefix: "", legal_name: "", address: "", tax_id: "", footer: "", account_codes: { income: "4000", cash: "1000", online: "1010", deposit: "2100" }, payment_terms_days: 14 };

function mount() {
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })}>
    <BillingDocumentsSettings makerspaceId={7} />
  </QueryClientProvider>);
  fireEvent.click(screen.getByRole("button", { name: "Configure documents" }));
}

beforeEach(() => { staffRequest.mockReset(); staffRequest.mockResolvedValue(policy); });

describe("Core billing documents settings", () => {
  it("saves presentation and mapping without rewriting billing terms", async () => {
    mount();
    fireEvent.change(await screen.findByLabelText("Number prefix"), { target: { value: "SW-" } });
    fireEvent.click(screen.getByRole("button", { name: "Save receipt settings" }));
    await waitFor(() => expect(staffRequest).toHaveBeenCalledWith("/admin/makerspace/7/billing-settings", {
      method: "PATCH", body: JSON.stringify({ number_prefix: "SW-", legal_name: "", address: "", tax_id: "", footer: "", account_codes: policy.account_codes }),
    }));
  });

  it("keeps invalid mapping JSON from reaching the server", async () => {
    mount();
    fireEvent.change(await screen.findByLabelText("Accounting account codes (JSON)"), { target: { value: "{" } });
    fireEvent.click(screen.getByRole("button", { name: "Save receipt settings" }));
    expect(await screen.findByRole("alert")).toBeVisible();
    expect(staffRequest).toHaveBeenCalledTimes(1);
  });
});
