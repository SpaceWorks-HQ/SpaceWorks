import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { EventRegisterMember } from "./EventRegisterMember";
import { StructuredApiError } from "../../lib/api";

const { staffRequest } = vi.hoisted(() => ({ staffRequest: vi.fn() }));

vi.mock("../../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../../lib/api")>("../../lib/api");
  return { ...actual, staffRequest };
});

function renderPanel() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <EventRegisterMember makerspaceId={7} eventId={3} customForm={null} disabled={false} />
    </QueryClientProvider>,
  );
}

const MEMBERS = [
  { member_id: 11, display_name: "Walk In A" },
  { member_id: 22, display_name: "Walk In B" },
];

function missingEmail() {
  return new StructuredApiError(400, { email: ["This field cannot be blank."] });
}

beforeEach(() => {
  staffRequest.mockReset();
  // The eligible-member list is the first call; the registration POST follows.
  staffRequest.mockImplementation((path: string) =>
    path.includes("eligible-members") ? Promise.resolve(MEMBERS) : Promise.reject(missingEmail()),
  );
});

describe("EventRegisterMember", () => {
  it("reveals the email field from the field-keyed error body, not the message", async () => {
    // `StructuredApiError.message` flattens values only, so it reads "This field cannot
    // be blank." with no field name. A prompt keyed on the message never appears.
    renderPanel();
    await screen.findByRole("option", { name: "Walk In A" });

    fireEvent.change(screen.getByLabelText("Register a member"), { target: { value: "11" } });
    fireEvent.click(screen.getByRole("button", { name: "Register" }));

    expect(await screen.findByLabelText("Contact email")).toBeTruthy();
  });

  it("clears a fallback contact when the selected member changes", async () => {
    // Otherwise walk-in B is registered with walk-in A's address -- and because B has no
    // account email either, the backend accepts it and B's event mail goes to A.
    renderPanel();
    await screen.findByRole("option", { name: "Walk In A" });
    const picker = screen.getByLabelText("Register a member");

    fireEvent.change(picker, { target: { value: "11" } });
    fireEvent.click(screen.getByRole("button", { name: "Register" }));
    const emailField = await screen.findByLabelText("Contact email");
    fireEvent.change(emailField, { target: { value: "walk-in-a@example.test" } });

    fireEvent.change(picker, { target: { value: "22" } });

    expect(screen.queryByLabelText("Contact email")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Register" }));
    await waitFor(() => {
      // The LAST POST: the first one is the deliberate failure that revealed the field.
      const posts = staffRequest.mock.calls.filter(([, init]) => init?.method === "POST");
      const post = posts[posts.length - 1];
      expect(post).toBeTruthy();
      const body = JSON.parse(post![1].body as string);
      expect(body.member_id).toBe(22);
      expect(body.email).toBeUndefined();
    });
  });
});
