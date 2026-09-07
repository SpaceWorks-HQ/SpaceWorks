import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { StructuredApiError } from "../../lib/api";
import { expectNoA11yViolations } from "../../test/axe";
import { DEPOSIT_REQUIRED_MESSAGE, issueErrorMessage } from "./issueErrors";
import { MakerspaceLoanSettings, validateLoanForm, type LoanSettings } from "./MakerspaceLoanSettings";

const { staffRequest } = vi.hoisted(() => ({ staffRequest: vi.fn() }));

vi.mock("../../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../../lib/api")>("../../lib/api");
  return { ...actual, staffRequest };
});

const settings: LoanSettings = {
  loan_deposit_mode: "fixed",
  loan_deposit_amount: "25.00",
  loan_late_fee_per_day: "1.50",
  loan_late_fee_cap: "30.00",
  loan_grace_days: 2,
  loan_deposit_blocks_issue: false,
};

function renderSettings() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MakerspaceLoanSettings makerspaceId={7} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  staffRequest.mockReset();
  staffRequest.mockImplementation(async (_path: string, options?: RequestInit) =>
    options?.method === "PATCH" ? { ...settings, ...JSON.parse(String(options.body)) } : settings);
});

describe("MakerspaceLoanSettings", () => {
  it("loads the six loan fields and saves them through the payment-settings endpoint", async () => {
    const { container } = renderSettings();

    expect(await screen.findByDisplayValue("25.00")).toBeVisible();
    expect(screen.getByRole("combobox", { name: "Deposit mode" })).toHaveValue("fixed");

    fireEvent.change(screen.getByRole("textbox", { name: /Grace days/ }), { target: { value: "5" } });
    fireEvent.click(screen.getByRole("checkbox", { name: /Deposit blocks issue/ }));
    fireEvent.click(screen.getByRole("button", { name: "Save loan settings" }));

    await waitFor(() => expect(staffRequest).toHaveBeenCalledWith(
      "/admin/makerspace/7/payment-settings",
      {
        method: "PATCH",
        body: JSON.stringify({
          loan_deposit_mode: "fixed",
          loan_deposit_amount: "25.00",
          loan_late_fee_per_day: "1.50",
          loan_late_fee_cap: "30.00",
          loan_grace_days: 5,
          loan_deposit_blocks_issue: true,
        }),
      },
    ));
    expect(await screen.findByRole("status")).toHaveTextContent("Saved.");

    await expectNoA11yViolations(container);
  });

  it("refuses negative money, fractional days and does not call the API", async () => {
    renderSettings();
    await screen.findByDisplayValue("25.00");

    fireEvent.change(screen.getByRole("textbox", { name: /Late fee per day/ }), { target: { value: "-1" } });
    fireEvent.change(screen.getByRole("textbox", { name: /Grace days/ }), { target: { value: "1.5" } });
    fireEvent.click(screen.getByRole("button", { name: "Save loan settings" }));

    expect(screen.getByText("Enter a non-negative amount with at most two decimals.")).toBeVisible();
    expect(screen.getByText("Enter a whole number of days (0 or more).")).toBeVisible();
    expect(staffRequest).not.toHaveBeenCalledWith(expect.anything(), expect.objectContaining({ method: "PATCH" }));

    expect(validateLoanForm({
      loan_deposit_mode: "none", loan_deposit_amount: "0", loan_late_fee_per_day: "0.5",
      loan_late_fee_cap: "0", loan_grace_days: "0", loan_deposit_blocks_issue: false,
    })).toEqual({});
  });
});

describe("issueErrorMessage", () => {
  it("names the deposit gate for 409 deposit_required and falls through otherwise", () => {
    const deposit = new StructuredApiError(409, { detail: "The loan deposit must be settled before issue.", code: "deposit_required" });
    expect(issueErrorMessage(deposit)).toBe(DEPOSIT_REQUIRED_MESSAGE);
    expect(issueErrorMessage(new StructuredApiError(409, { detail: "Evidence has not been uploaded.", code: "evidence_not_uploaded" })))
      .toBe("Evidence has not been uploaded.");
    expect(issueErrorMessage("boom", "Request failed")).toBe("Request failed");
  });
});
