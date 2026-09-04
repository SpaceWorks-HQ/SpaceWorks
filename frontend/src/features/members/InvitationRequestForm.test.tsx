import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { StructuredApiError } from "../../lib/api";
import { expectNoA11yViolations } from "../../test/axe";
import { InvitationRequestForm } from "./InvitationRequestForm";

const { tenantPublicRequest } = vi.hoisted(() => ({ tenantPublicRequest: vi.fn() }));

vi.mock("../../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../../lib/api")>("../../lib/api");
  return { ...actual, tenantPublicRequest };
});

function renderForm() {
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <InvitationRequestForm slug="community-lab" />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  tenantPublicRequest.mockReset();
  tenantPublicRequest.mockResolvedValue({ detail: "Thanks - the makerspace will be in touch." });
});

describe("InvitationRequestForm", () => {
  it("posts the visitor's details with an empty honeypot and shows the backend acknowledgement", async () => {
    const { container } = renderForm();

    // The honeypot is present for bots but never exposed to people.
    const honeypot = container.querySelector<HTMLInputElement>('input[name="website"]');
    expect(honeypot).not.toBeNull();
    expect(honeypot?.closest(".hidden")).not.toBeNull();
    expect(screen.queryByRole("textbox", { name: "Website" })).not.toBeInTheDocument();

    expect(screen.getByRole("button", { name: "Send request" })).toBeDisabled();
    fireEvent.change(screen.getByRole("textbox", { name: "Name" }), { target: { value: "Ada Lovelace" } });
    fireEvent.change(screen.getByRole("textbox", { name: "Email" }), { target: { value: "ada@example.com" } });
    fireEvent.change(screen.getByRole("textbox", { name: "Message (optional)" }), { target: { value: "Robotics club" } });
    fireEvent.click(screen.getByRole("button", { name: "Send request" }));

    await waitFor(() => expect(tenantPublicRequest).toHaveBeenCalledWith(
      "community-lab",
      "/public/community-lab/invitation-requests",
      {
        method: "POST",
        body: JSON.stringify({ name: "Ada Lovelace", email: "ada@example.com", phone: "", message: "Robotics club", website: "" }),
      },
    ));
    expect(await screen.findByRole("status")).toHaveTextContent("Thanks - the makerspace will be in touch.");

    await expectNoA11yViolations(container);
  });

  it("explains a throttle or a closed queue instead of a raw status", async () => {
    tenantPublicRequest.mockRejectedValue(new StructuredApiError(429, { detail: "Request was throttled." }));
    renderForm();

    fireEvent.change(screen.getByRole("textbox", { name: "Name" }), { target: { value: "Ada" } });
    fireEvent.change(screen.getByRole("textbox", { name: "Email" }), { target: { value: "ada@example.com" } });
    fireEvent.click(screen.getByRole("button", { name: "Send request" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Too many requests from this connection.");
  });
});
