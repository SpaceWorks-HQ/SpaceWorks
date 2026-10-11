import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";

import { EmailLogPanel } from "./EmailLogPanel";
import type { Makerspace } from "./shared";

const { query } = vi.hoisted(() => ({ query: vi.fn() }));
vi.mock("./shared", async () => {
  const actual = await vi.importActual<typeof import("./shared")>("./shared");
  return { ...actual, useStaffGet: query };
});

it("filters skipped email, displays its reason and offers no retry", () => {
  query.mockReturnValue({ data: { count: 1, next: null, previous: null, results: [{
    id: 1, status: "skipped", error: "Email is disabled for this makerspace.",
    created_at: "2026-10-10T00:00:00Z", to_email: "member@example.org", event: "accepted",
  }] }, isLoading: false });
  render(<QueryClientProvider client={new QueryClient()}>
    <MemoryRouter>
    <EmailLogPanel makerspace={{ id: 7, slug: "lab" } as Makerspace} />
    </MemoryRouter>
  </QueryClientProvider>);
  fireEvent.change(screen.getByRole("combobox", { name: "Email log status" }), { target: { value: "skipped" } });
  expect(query).toHaveBeenLastCalledWith(
    ["email-logs", 7, "status=skipped&page=1"], "/admin/makerspace/7/email-logs?status=skipped&page=1",
  );
  expect(screen.getByText("Email is disabled for this makerspace.")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Retry" })).toBeNull();
});

it("restores the dashboard's failed-in-seven-days filter and page from the URL", () => {
  query.mockReturnValue({ data: { count: 0, results: [] }, isLoading: false });
  render(<QueryClientProvider client={new QueryClient()}>
    <MemoryRouter initialEntries={["/admin/email-log?status=failed&recent_days=7&page=2"]}>
      <EmailLogPanel makerspace={{ id: 7, slug: "lab" } as Makerspace} />
    </MemoryRouter>
  </QueryClientProvider>);
  expect(query).toHaveBeenLastCalledWith(["email-logs", 7, "status=failed&recent_days=7&page=2"], "/admin/makerspace/7/email-logs?status=failed&recent_days=7&page=2");
  expect(screen.getByRole("combobox", { name: "Email log status" })).toHaveValue("failed");
});
