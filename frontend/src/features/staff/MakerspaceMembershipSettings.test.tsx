import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { MakerspaceMembershipSettings } from "./MakerspaceMembershipSettings";
import type { Makerspace } from "./StaffPanels";

const { staffRequest } = vi.hoisted(() => ({ staffRequest: vi.fn() }));
vi.mock("../../lib/api", () => ({ staffRequest }));

const makerspace: Makerspace = {
  id: 7, name: "Test lab", public_code: "TEST", slug: "test-lab",
  telegram_group_chat_id: "", frontend_domain: null, hidden_from_central_directory: false,
};

function renderSettings() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  // The settings panel owns this query; this child consumes its server state as props.
  function SettingsPanel() {
    const settings = useQuery({
      queryKey: ["makerspace-settings", makerspace.id],
      queryFn: () => staffRequest(`/admin/makerspaces/${makerspace.id}`) as Promise<Makerspace>,
    });
    return <MakerspaceMembershipSettings makerspace={makerspace} settings={settings.data} loading={settings.isLoading} />;
  }
  render(<QueryClientProvider client={client}><SettingsPanel /></QueryClientProvider>);
  return client;
}

beforeEach(() => staffRequest.mockReset());

describe("MakerspaceMembershipSettings lapsed-member toggle", () => {
  it("saves the API field, blocks repeat clicks while pending, and refreshes server state", async () => {
    let enabled = false;
    let complete: () => void = () => {};
    const pending = new Promise<void>((resolve) => { complete = resolve; });
    staffRequest.mockImplementation(async (_path: string, options?: RequestInit) => {
      if (options?.method === "PATCH") {
        await pending;
        enabled = JSON.parse(String(options.body)).lapsed_members_cannot_borrow;
      }
      return { ...makerspace, lapsed_members_cannot_borrow: enabled };
    });
    const client = renderSettings();
    // These other lists must refresh too: the policy travels on their makerspace rows.
    client.setQueryData(["makerspaces"], [makerspace]);
    client.setQueryData(["staff", "makerspaces"], [makerspace]);
    const checkbox = await screen.findByRole("checkbox", { name: "Lapsed members cannot borrow" });
    expect(checkbox).not.toBeChecked();

    fireEvent.click(checkbox);
    await waitFor(() => expect(checkbox).toBeDisabled());
    expect(staffRequest).toHaveBeenCalledWith("/admin/makerspaces/7", {
      method: "PATCH", body: JSON.stringify({ lapsed_members_cannot_borrow: true }),
    });
    complete();

    await waitFor(() => expect(checkbox).toBeChecked());
    expect(checkbox).toBeEnabled();
    expect(screen.getByText("Cannot borrow")).toBeVisible();
    expect(client.getQueryState(["makerspaces"])?.isInvalidated).toBe(true);
    expect(client.getQueryState(["staff", "makerspaces"])?.isInvalidated).toBe(true);
  });

  it("shows a refused save and keeps the last server value available for retry", async () => {
    staffRequest.mockImplementation(async (_path: string, options?: RequestInit) => {
      if (options?.method === "PATCH") throw new Error("Settings could not be saved.");
      return { ...makerspace, lapsed_members_cannot_borrow: false };
    });
    renderSettings();
    const checkbox = await screen.findByRole("checkbox", { name: "Lapsed members cannot borrow" });

    fireEvent.click(checkbox);

    expect(await screen.findByRole("alert")).toHaveTextContent("Settings could not be saved.");
    expect(checkbox).not.toBeChecked();
    expect(checkbox).toBeEnabled();
  });

  it("waits for the settings field before offering a policy change", async () => {
    staffRequest.mockResolvedValue(makerspace);
    const client = renderSettings();
    await waitFor(() => expect(client.getQueryState(["makerspace-settings", 7])?.status).toBe("success"));

    expect(screen.queryByRole("checkbox", { name: "Lapsed members cannot borrow" })).not.toBeInTheDocument();
  });

  it("disables a loaded policy while the parent settings query is loading", () => {
    const client = new QueryClient();
    render(<QueryClientProvider client={client}>
      <MakerspaceMembershipSettings makerspace={makerspace} settings={{ ...makerspace, lapsed_members_cannot_borrow: true }} loading />
    </QueryClientProvider>);

    expect(screen.getByRole("checkbox", { name: "Lapsed members cannot borrow" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Lapsed members cannot borrow" })).toBeDisabled();
    expect(staffRequest).not.toHaveBeenCalled();
  });
});
