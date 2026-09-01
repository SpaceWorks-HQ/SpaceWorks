/**
 * The account-less borrow form must actually be submittable.
 *
 * `setup.sh` offers "anyone, no account needed" and the backend implements it, but the
 * public form used to send only `{requested_for, items}`. The backend REQUIRES
 * `contact_name`, `contact_email` and an `Idempotency-Key` header on an anonymous
 * submission, so every visitor to an opted-in makerspace received a 400 — an advertised
 * mode that could not be used. These pin the client half of that contract: the fields are
 * collected, the header is sent, and a members-only space is left untouched.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { submitPublicRequest, getAccessToken, refreshAccessToken } = vi.hoisted(() => ({
  submitPublicRequest: vi.fn(),
  getAccessToken: vi.fn(),
  refreshAccessToken: vi.fn(),
}));

vi.mock("./api", async () => {
  const actual = await vi.importActual<typeof import("./api")>("./api");
  return { ...actual, submitPublicRequest };
});

vi.mock("../../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../../lib/api")>("../../lib/api");
  return { ...actual, getAccessToken, refreshAccessToken };
});

import { PublicRequestPanel } from "./PublicRequestPanel";

const ITEMS = [{ productId: 7, name: "Logic analyzer", quantity: 1 }];

function fill(label: RegExp, value: string) {
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
}

function renderPanel(accountLess: boolean) {
  // The panel derives account-less mode from policy AND the absence of an access token.
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <PublicRequestPanel
        requestAccess={accountLess ? "anyone" : undefined}
        items={ITEMS}
        makerspaceSlug="makerspace"
        onClear={() => {}}
      />
    </QueryClientProvider>,
  );
}

describe("account-less borrow requests", () => {
  beforeEach(() => {
    submitPublicRequest.mockReset();
    submitPublicRequest.mockResolvedValue({ public_token: "tok-abc-123" });
    getAccessToken.mockReset();
    getAccessToken.mockReturnValue("");
    refreshAccessToken.mockReset();
    // No session to restore: the panel probes the refresh cookie before deciding, so an
    // anonymous visitor is only known to be anonymous once this settles.
    refreshAccessToken.mockResolvedValue(false);
  });

  // The account-less form appears only after the session probe settles.
  async function awaitAccountLessForm() {
    await waitFor(() => expect(screen.getByLabelText(/your name/i)).toBeTruthy());
  }

  it("collects contact details and sends them with an idempotency key", async () => {
    renderPanel(true);
    await awaitAccountLessForm();

    fill(/your name/i, "Ada Lovelace");
    fill(/^email$/i, "ada@example.test");
    fill(/request purpose/i, "Bench diagnostics");
    fireEvent.click(screen.getByRole("button", { name: /submit request/i }));

    await waitFor(() => expect(submitPublicRequest).toHaveBeenCalledTimes(1));
    const [slug, payload, idempotencyKey] = submitPublicRequest.mock.calls[0];
    expect(slug).toBe("makerspace");
    expect(payload).toMatchObject({
      requested_for: "Bench diagnostics",
      contact_name: "Ada Lovelace",
      contact_email: "ada@example.test",
    });
    expect(payload.items).toEqual([{ product_id: 7, quantity: 1 }]);
    // Required by the backend; without it an anonymous submission is refused outright.
    expect(idempotencyKey).toBeTruthy();
  });

  it("keeps submit disabled until a name and an email are given", async () => {
    renderPanel(true);
    await awaitAccountLessForm();

    fill(/request purpose/i, "Bench diagnostics");
    expect(screen.getByRole("button", { name: /submit request/i })).toBeDisabled();

    fill(/your name/i, "Ada Lovelace");
    expect(screen.getByRole("button", { name: /submit request/i })).toBeDisabled();

    fill(/^email$/i, "ada@example.test");
    expect(screen.getByRole("button", { name: /submit request/i })).toBeEnabled();
  });

  it("shows the request token afterwards, the only handle an account-less visitor has", async () => {
    renderPanel(true);
    await awaitAccountLessForm();

    fill(/your name/i, "Ada Lovelace");
    fill(/^email$/i, "ada@example.test");
    fill(/request purpose/i, "Bench diagnostics");
    fireEvent.click(screen.getByRole("button", { name: /submit request/i }));

    // Unverified contacts get no lifecycle email and there is no signed-in area to return
    // to, so discarding the token would strand the requester.
    await waitFor(() => expect(screen.getByText("tok-abc-123")).toBeTruthy());
  });

  it("sends the honeypot field so autofill bots get the decoy response", async () => {
    const { container } = renderPanel(true);
    await awaitAccountLessForm();

    fill(/your name/i, "Ada Lovelace");
    fill(/^email$/i, "ada@example.test");
    fill(/request purpose/i, "Bench diagnostics");
    // Queried by name, not by role: the wrapper is aria-hidden precisely so assistive
    // technology never offers it, which is what makes it a honeypot.
    const honeypot = container.querySelector('input[name="website"]');
    expect(honeypot).not.toBeNull();
    fireEvent.change(honeypot as HTMLInputElement, {
      target: { value: "http://spam.example" },
    });
    fireEvent.click(screen.getByRole("button", { name: /submit request/i }));

    await waitFor(() => expect(submitPublicRequest).toHaveBeenCalledTimes(1));
    expect(submitPublicRequest.mock.calls[0][1].website).toBe("http://spam.example");
  });

  it("gives a signed-in member the member form even on an opted-in space", async () => {
    // `tenantPublicRequest` still attaches Authorization, so the backend takes the
    // authenticated branch and ignores contact fields. Asking for them would promise
    // something the stored request does not honour.
    getAccessToken.mockReturnValue("an-access-token");
    renderPanel(true);

    expect(screen.queryByLabelText(/your name/i)).toBeNull();
    // An `anyone` policy has the membership module off, so the copy must NOT claim
    // membership, waiver and presence are required.
    await waitFor(() =>
      expect(screen.getByText(/filed against your account/i)).toBeTruthy(),
    );
    expect(screen.queryByLabelText(/your name/i)).toBeNull();
  });

  it("does not promise 'no account needed' on the scan tab", async () => {
    renderPanel(true);
    await waitFor(() => expect(screen.getByText(/no account needed/i)).toBeTruthy());

    fireEvent.click(screen.getByRole("button", { name: /scan a tool/i }));

    // Self-checkout requires an authenticated member with active presence.
    expect(screen.queryByText(/no account needed/i)).toBeNull();
  });

  it("asks a members-only space for no contact details and sends no key", async () => {
    renderPanel(false);

    expect(screen.queryByLabelText(/your name/i)).toBeNull();
    fill(/request purpose/i, "Bench diagnostics");
    fireEvent.click(screen.getByRole("button", { name: /submit request/i }));

    await waitFor(() => expect(submitPublicRequest).toHaveBeenCalledTimes(1));
    const [, payload, idempotencyKey] = submitPublicRequest.mock.calls[0];
    expect(payload).not.toHaveProperty("contact_name");
    expect(idempotencyKey).toBeUndefined();
  });
});
