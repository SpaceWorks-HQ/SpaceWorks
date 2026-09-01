import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiClientsPanel } from "./ApiClientsPanel";
import type { ApiClient, ApiClientScopeOption } from "./apiClientsApi";
import type { Makerspace } from "./StaffPanels";


const { query, staffRequest } = vi.hoisted(() => ({
  query: vi.fn(),
  staffRequest: vi.fn(),
}));

vi.mock("../../lib/api", () => ({ staffRequest }));
vi.mock("./StaffPanels", async () => {
  const actual = await vi.importActual<typeof import("./StaffPanels")>("./StaffPanels");
  return { ...actual, useStaffGet: query };
});

const scopes: ApiClientScopeOption[] = [
  { value: "public:read", label: "Public read", description: "Read public routes.", group: "Public API", grantable: true, lock_reason: null },
  { value: "public:write", label: "Public write", description: "Write public routes.", group: "Public API", grantable: true, lock_reason: null },
  { value: "admin:write", label: "Admin write", description: "Write admin routes.", group: "Operator-only", grantable: true, lock_reason: null },
  { value: "admin:*", label: "All admin access", description: "All admin routes.", group: "Operator-only", grantable: true, lock_reason: null },
  { value: "legacy:v1", label: "Legacy v1 compatibility", description: "Frozen cutover access.", group: "Legacy", grantable: false, lock_reason: "Only a global superadmin may grant this scope." },
];

const legacyClient: ApiClient = {
  id: 9,
  label: "Legacy client",
  client_id: "ck_legacy",
  client_type: "server",
  last_seen_at: null,
  allowed_origins: ["https://lab.example"],
  scopes: ["legacy:v1"],
  is_active: true,
  created_at: "2026-08-20T00:00:00Z",
};

const makerspace = {
  id: 7,
  name: "Community Lab",
  public_code: "community-lab",
  slug: "community-lab",
  telegram_group_chat_id: "",
  frontend_domain: null,
  hidden_from_central_directory: false,
} as Makerspace;

function configureQueries(scopeError: Error | null = null, clients = [legacyClient]) {
  query.mockImplementation((key: unknown[]) => {
    if (key[0] === "api-clients") {
      return { data: { results: clients }, isLoading: false, error: null };
    }
    if (key[0] === "api-client-scopes") {
      return {
        data: scopeError ? undefined : { count: scopes.length, next: null, previous: null, results: scopes },
        isLoading: false,
        error: scopeError,
      };
    }
    if (key[0] === "api-key-requests") {
      return { data: { results: [] }, isLoading: false, error: null };
    }
    return { data: undefined, isLoading: false, error: null };
  });
}

function renderPanel() {
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  const invalidate = vi.spyOn(client, "invalidateQueries");
  render(
    <QueryClientProvider client={client}>
      <ApiClientsPanel makerspace={makerspace} isSuperadmin={false} canManageMakerspace />
    </QueryClientProvider>,
  );
  return invalidate;
}

beforeEach(() => {
  query.mockReset();
  staffRequest.mockReset();
  configureQueries();
});

describe("ApiClientsPanel scope picker", () => {
  it("requires an explicit scope and sends it on create", async () => {
    staffRequest.mockResolvedValue({ ...legacyClient, id: 10, client_secret: "shown-once", scopes: ["public:read"] });
    const invalidate = renderPanel();
    const createCard = screen.getByText("API clients").closest("article")!;
    const create = within(createCard);

    fireEvent.change(create.getByLabelText("Client label"), { target: { value: "Public app" } });
    fireEvent.change(create.getByPlaceholderText(/allowed browser origins/i), { target: { value: "https://app.example" } });
    expect(create.getByRole("button", { name: /create api client/i })).toBeDisabled();
    expect(create.getByRole("checkbox", { name: /legacy v1/i })).toBeDisabled();
    fireEvent.click(create.getByRole("checkbox", { name: /legacy v1/i }));
    fireEvent.click(create.getByRole("checkbox", { name: /public read/i }));
    fireEvent.click(create.getByRole("button", { name: /create api client/i }));

    await waitFor(() => expect(staffRequest).toHaveBeenCalled());
    expect(JSON.parse(staffRequest.mock.calls[0][1]?.body as string)).toEqual({
      label: "Public app", allowed_origins: ["https://app.example"], scopes: ["public:read"],
    });
    await waitFor(() => expect(invalidate).toHaveBeenCalledWith({ queryKey: ["api-clients", 7] }));
  });

  it("warns about legacy access and sends an explicit replacement PATCH", async () => {
    staffRequest.mockResolvedValue({ ...legacyClient, scopes: ["public:write"] });
    const invalidate = renderPanel();
    const row = screen.getByText("Legacy client").closest("div.rounded-md") as HTMLElement;
    const editor = within(row);

    expect(editor.getByText(/legacy v1 access preserves/i)).toBeTruthy();
    fireEvent.click(editor.getByRole("checkbox", { name: /public write/i }));
    fireEvent.click(editor.getByRole("button", { name: /save scopes/i }));

    await waitFor(() => expect(staffRequest).toHaveBeenCalledWith(
      "/admin/api-clients/9",
      { method: "PATCH", body: JSON.stringify({ scopes: ["public:write"] }) },
    ));
    await waitFor(() => expect(invalidate).toHaveBeenCalledWith({ queryKey: ["api-clients", 7] }));
  });

  it("locks browser-incompatible scopes and PATCHes only selectable scopes", async () => {
    const browserClient = {
      ...legacyClient,
      label: "Browser client",
      client_type: "browser" as const,
      scopes: ["public:read"],
    };
    configureQueries(null, [browserClient]);
    staffRequest.mockResolvedValue({ ...browserClient, scopes: ["public:read", "public:write"] });
    renderPanel();
    const row = screen.getByText("Browser client").closest("div.rounded-md") as HTMLElement;
    const editor = within(row);

    expect(editor.getByRole("checkbox", { name: /admin write/i })).toBeDisabled();
    expect(editor.getByRole("checkbox", { name: /all admin access/i })).toBeDisabled();
    expect(editor.getAllByText(/browser clients may only use public\/read scopes/i)).toHaveLength(2);
    fireEvent.click(editor.getByRole("checkbox", { name: /admin write/i }));
    fireEvent.click(editor.getByRole("checkbox", { name: /public write/i }));
    fireEvent.click(editor.getByRole("button", { name: /save scopes/i }));

    await waitFor(() => expect(staffRequest).toHaveBeenCalledWith(
      "/admin/api-clients/9",
      { method: "PATCH", body: JSON.stringify({ scopes: ["public:read", "public:write"] }) },
    ));
  });

  it("renders catalog errors and leaves create disabled", () => {
    configureQueries(new Error("Scope catalog unavailable"));
    renderPanel();

    expect(screen.getAllByText("Scope catalog unavailable").length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: /create api client/i })).toBeDisabled();
  });

  it("renders create failures without invalidating the client list", async () => {
    staffRequest.mockRejectedValue(new Error("Create failed"));
    const invalidate = renderPanel();
    const create = within(screen.getByText("API clients").closest("article")!);
    fireEvent.change(create.getByLabelText("Client label"), { target: { value: "Bad app" } });
    fireEvent.change(create.getByPlaceholderText(/allowed browser origins/i), { target: { value: "https://bad.example" } });
    fireEvent.click(create.getByRole("checkbox", { name: /public read/i }));
    fireEvent.click(create.getByRole("button", { name: /create api client/i }));

    await waitFor(() => expect(create.getByText("Create failed")).toBeTruthy());
    expect(invalidate).not.toHaveBeenCalledWith({ queryKey: ["api-clients", 7] });
  });
});
