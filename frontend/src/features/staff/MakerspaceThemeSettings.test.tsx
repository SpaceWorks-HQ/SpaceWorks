import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { staffRequest } from "../../lib/api";
import { MakerspaceThemeSettings } from "./MakerspaceThemeSettings";
import type { Makerspace } from "./StaffPanels";

vi.mock("../../lib/api", () => ({ staffRequest: vi.fn() }));
afterEach(() => { vi.clearAllMocks(); });
const space = { id: 7, name: "Brand", slug: "brand" } as Makerspace;

function show() {
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  const invalidate = vi.spyOn(client, "invalidateQueries");
  render(<QueryClientProvider client={client}><MakerspaceThemeSettings makerspace={space} settings={{ ...space, theme_config: { mode: "system", primary_color: "", accent_color: "", logo_url: "https://example.com/logo.png" } }} loading={false} /></QueryClientProvider>);
  return invalidate;
}

it("previews both modes and names the failing contrast pairs live", () => {
  show();
  fireEvent.change(screen.getByLabelText("Primary fill"), { target: { value: "#777" } });
  expect(screen.getByTestId("theme-preview-light")).toHaveTextContent("AA 4.5:1");
  expect(screen.getByTestId("theme-preview-dark")).toHaveTextContent("AA 3:1");
  expect(screen.getByText(/light: on-secondary\/80 on secondary is/)).toBeVisible();
  expect(screen.getByText(/dark: on-secondary\/80 on secondary is/)).toBeVisible();
  expect(screen.getByRole("button", { name: "Save colours" })).toBeDisabled();
  expect(screen.getByTestId("theme-preview-light")).toHaveTextContent("Product palette fallback shown");
  fireEvent.change(screen.getByLabelText("Primary fill"), { target: { value: "red" } });
  expect(screen.getByText(/primary_color must be a #RGB/)).toBeVisible();
});

it("prevents a write before settings are available", () => {
  const client = new QueryClient();
  render(<QueryClientProvider client={client}><MakerspaceThemeSettings makerspace={space} loading={false} /></QueryClientProvider>);
  fireEvent.change(screen.getByLabelText("Primary fill"), { target: { value: "#004400" } });
  expect(screen.getByRole("button", { name: "Save colours" })).toBeDisabled();
  expect(staffRequest).not.toHaveBeenCalled();
});

it("can repair malformed restored colour values without crashing the editor", () => {
  const client = new QueryClient();
  render(<QueryClientProvider client={client}><MakerspaceThemeSettings makerspace={space} settings={{ ...space, theme_config: { primary_color: 0, accent_color: false } as unknown as Record<string, string> }} loading={false} /></QueryClientProvider>);
  expect(screen.getByLabelText("Primary fill")).toHaveValue("");
  expect(screen.getByLabelText("Link colour seed")).toHaveValue("");
  fireEvent.change(screen.getByLabelText("Primary fill"), { target: { value: "#004400" } });
  expect(screen.getByRole("button", { name: "Save colours" })).toBeEnabled();
});

it("invalidates the submitted tenant when a save finishes after tenant navigation", async () => {
  let finish!: (result: Makerspace) => void;
  vi.mocked(staffRequest).mockImplementation(() => new Promise((resolve) => { finish = resolve as typeof finish; }));
  const client = new QueryClient();
  const invalidate = vi.spyOn(client, "invalidateQueries");
  const view = render(<QueryClientProvider client={client}><MakerspaceThemeSettings makerspace={space} settings={space} loading={false} /></QueryClientProvider>);
  fireEvent.change(screen.getByLabelText("Primary fill"), { target: { value: "#004400" } });
  fireEvent.click(screen.getByRole("button", { name: "Save colours" }));
  await waitFor(() => expect(staffRequest).toHaveBeenCalled());
  const other = { ...space, id: 8, slug: "other" };
  view.rerender(<QueryClientProvider client={client}><MakerspaceThemeSettings makerspace={other} settings={other} loading={false} /></QueryClientProvider>);
  await act(async () => finish(space));
  await waitFor(() => expect(invalidate).toHaveBeenCalledWith({ queryKey: ["tenant-bootstrap", "brand"] }));
  expect(invalidate).toHaveBeenCalledWith({ queryKey: ["makerspace-settings", 7] });
  expect(invalidate).not.toHaveBeenCalledWith({ queryKey: ["tenant-bootstrap", "other"] });
  expect(screen.getByLabelText("Primary fill")).toHaveValue("");
});

it("saves valid colours, preserves unrelated theme keys and refreshes public/member caches", async () => {
  vi.mocked(staffRequest).mockResolvedValue(space);
  const invalidate = show();
  fireEvent.change(screen.getByLabelText("Primary fill"), { target: { value: "#004400" } });
  expect(screen.getByTestId("theme-preview-light").style.getPropertyValue("--color-on-secondary")).toBe("255 255 255");
  expect(screen.getByTestId("theme-preview-dark").style.getPropertyValue("--color-secondary-ink")).not.toBe(screen.getByTestId("theme-preview-light").style.getPropertyValue("--color-secondary-ink"));
  fireEvent.click(screen.getByRole("button", { name: "Save colours" }));
  await waitFor(() => expect(staffRequest).toHaveBeenCalledWith("/admin/makerspaces/7", {
    method: "PATCH", body: JSON.stringify({ theme_config: { mode: "system", primary_color: "#004400", accent_color: "", logo_url: "https://example.com/logo.png" } }),
  }));
  await waitFor(() => expect(invalidate).toHaveBeenCalledWith({ queryKey: ["tenant-bootstrap", "brand"] }));
  expect(invalidate).toHaveBeenCalledWith({ queryKey: ["member"] });
  expect(invalidate).toHaveBeenCalledWith({ queryKey: ["runtime-tenant-origin"] });
});

it("shows backend write failures and keeps the entered palette", async () => {
  vi.mocked(staffRequest).mockRejectedValue(new Error("Permission denied"));
  show();
  fireEvent.change(screen.getByLabelText("Primary fill"), { target: { value: "#004400" } });
  fireEvent.click(screen.getByRole("button", { name: "Save colours" }));
  expect(await screen.findByText("Permission denied")).toBeVisible();
  expect(screen.getByLabelText("Primary fill")).toHaveValue("#004400");
});
