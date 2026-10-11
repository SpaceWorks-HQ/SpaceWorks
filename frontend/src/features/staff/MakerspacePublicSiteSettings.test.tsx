import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { staffRequest } from "../../lib/api";
import { MakerspacePublicSiteSettings } from "./MakerspacePublicSiteSettings";

vi.mock("../../lib/api", () => ({ staffRequest: vi.fn() }));
const space = { id: 7, name: "Lab", slug: "lab", public_code: "LAB1", telegram_group_chat_id: "",
  frontend_domain: null, hidden_from_central_directory: false, public_site_enabled: true,
  public_landing_page: "auto" as const };

beforeEach(() => vi.clearAllMocks());

it("updates publication and invalidates every bootstrap including the member portal", async () => {
  vi.mocked(staffRequest).mockResolvedValue({ ...space, public_site_enabled: false });
  const cache = new QueryClient();
  const keys = [["tenant-bootstrap", "lab"], ["runtime-tenant", "lab"],
    ["member", "lab", "bootstrap"], ["public-makerspaces"], ["staff", "makerspaces"]];
  for (const key of keys) cache.setQueryData(key, space);
  render(<QueryClientProvider client={cache}><MakerspacePublicSiteSettings makerspace={space} loading={false} /></QueryClientProvider>);
  fireEvent.click(screen.getByRole("checkbox", { name: "Publish public site" }));
  await waitFor(() => expect(staffRequest).toHaveBeenCalledWith("/admin/makerspaces/7", {
    method: "PATCH", body: JSON.stringify({ public_site_enabled: false }),
  }));
  await waitFor(() => {
    for (const key of keys) expect(cache.getQueryState(key)?.isInvalidated).toBe(true);
  });
});

it("writes an explicit home choice and surfaces an API failure", async () => {
  vi.mocked(staffRequest).mockRejectedValue(new Error("Unable to save public home"));
  render(<QueryClientProvider client={new QueryClient()}><MakerspacePublicSiteSettings makerspace={space} loading={false} /></QueryClientProvider>);
  fireEvent.change(screen.getByRole("combobox", { name: "Public home" }), { target: { value: "bookings" } });
  expect(await screen.findByRole("alert")).toHaveTextContent("Unable to save public home");
  expect(staffRequest).toHaveBeenCalledWith("/admin/makerspaces/7", {
    method: "PATCH", body: JSON.stringify({ public_landing_page: "bookings" }),
  });
});
