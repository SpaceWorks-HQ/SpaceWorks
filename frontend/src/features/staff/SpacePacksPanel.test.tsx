import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { SpacePacksPanel } from "./SpacePacksPanel";

const { staffRequest } = vi.hoisted(() => ({ staffRequest: vi.fn() }));
vi.mock("../../lib/api", () => ({ staffRequest }));

const pack = { format: "spaceworks-space-pack", version: 1, configuration: { settings: {} }, checksum: "a".repeat(64) };
const preview = { applied: false, base_checksum: "b".repeat(64), changes: [
  { section: "settings", key: "settings", before: {}, after: { default_loan_days: 7 } },
] };

function mount(superadmin = false) {
  const queries = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const invalidate = vi.spyOn(queries, "invalidateQueries");
  render(<QueryClientProvider client={queries}><SpacePacksPanel makerspaceId={7} isSuperadmin={superadmin} /></QueryClientProvider>);
  return invalidate;
}

beforeEach(() => {
  staffRequest.mockReset();
  staffRequest.mockImplementation(async (path: string, options?: RequestInit) => {
    if (path.includes("space-pack-profiles")) return { count: 0, next: null, previous: null, results: [] };
    if (!options?.method) return pack;
    const body = JSON.parse(String(options.body));
    return body.dry_run ? preview : { ...preview, applied: true };
  });
});

describe("SpacePacksPanel", () => {
  it("requires a preview, sends its checksum on apply and refreshes server state", async () => {
    const invalidate = mount();
    const apply = screen.getByRole("button", { name: "Apply reviewed pack" });
    expect(apply).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Export configuration" }));
    await waitFor(() => expect(screen.getByRole("textbox", { name: "Space pack JSON" })).toHaveValue(JSON.stringify(pack, null, 2)));
    fireEvent.click(screen.getByRole("button", { name: "Preview import" }));
    await screen.findByText("Preview ready. No configuration changed.");
    expect(apply).toBeEnabled();
    fireEvent.click(apply);
    await screen.findByText("Pack applied.");
    expect(staffRequest).toHaveBeenCalledWith("/admin/makerspace/7/space-pack", {
      method: "POST", body: JSON.stringify({ pack, dry_run: false, base_checksum: preview.base_checksum }),
    });
    expect(invalidate).toHaveBeenCalledWith();
    expect(apply).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Save platform profile" })).not.toBeInTheDocument();
  });

  it("invalidates the preview after editing and does not submit malformed JSON", async () => {
    mount();
    const editor = screen.getByRole("textbox", { name: "Space pack JSON" });
    fireEvent.change(editor, { target: { value: JSON.stringify(pack) } });
    fireEvent.click(screen.getByRole("button", { name: "Preview import" }));
    await screen.findByText("Preview ready. No configuration changed.");
    fireEvent.change(editor, { target: { value: "broken" } });
    expect(screen.getByRole("button", { name: "Apply reviewed pack" })).toBeDisabled();
    const calls = staffRequest.mock.calls.length;
    fireEvent.click(screen.getByRole("button", { name: "Preview import" }));
    await screen.findByRole("alert");
    expect(staffRequest.mock.calls).toHaveLength(calls);
  });

  it("shows saved profiles only to a superadmin and saves a named snapshot", async () => {
    mount(true);
    fireEvent.change(screen.getByRole("textbox", { name: "Space pack JSON" }), { target: { value: JSON.stringify(pack) } });
    fireEvent.change(screen.getByRole("textbox", { name: "New install profile name" }), { target: { value: "Library" } });
    fireEvent.click(screen.getByRole("button", { name: "Save platform profile" }));
    await screen.findByText("Install profile saved.");
    expect(staffRequest).toHaveBeenCalledWith("/admin/space-pack-profiles", {
      method: "POST", body: JSON.stringify({ name: "Library", pack }),
    });
  });
});
