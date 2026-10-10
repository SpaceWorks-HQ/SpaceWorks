import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, it, vi } from "vitest";

const { bootstrapTenant, memberRequest } = vi.hoisted(() => ({ bootstrapTenant: vi.fn(), memberRequest: vi.fn() }));
vi.mock("../../lib/api", async () => ({
  ...await vi.importActual<typeof import("../../lib/api")>("../../lib/api"),
  bootstrapTenant, memberRequest, refreshAccessToken: vi.fn().mockResolvedValue(undefined),
}));
import { MemberArea } from "./MemberArea";

afterEach(() => { vi.restoreAllMocks(); });

it("renders member support contacts and scopes brand colours to the member main", async () => {
  bootstrapTenant.mockResolvedValue({
    makerspace: { id: 7, slug: "brand-space", name: "Brand Space", membership_policy: "invite_only" },
    modules: [], theme: { primary_color: "#fff", accent_color: "#000" },
    branding: { support_email: "help@example.com", support_url: "https://example.com/help" },
  });
  memberRequest.mockImplementation(async (path: string) => {
    if (path === "/memberships/me") return { memberships: [], requests: [] };
    if (path === "/memberships/invitations") return { invitations: [] };
    if (path.endsWith("payments")) return [];
    return {};
  });
  const tokens: Record<string, string> = {
    "on-secondary": "90 22 51", secondary: "249 168 212",
    bg: "250 249 244", surface: "239 238 233", panel: "255 255 255",
  };
  vi.spyOn(window, "getComputedStyle").mockReturnValue({
    getPropertyValue: (name: string) => tokens[name.replace("--color-", "")] ?? "",
  } as CSSStyleDeclaration);
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <MemoryRouter><MemberArea /></MemoryRouter>
  </QueryClientProvider>);
  expect(await screen.findByRole("link", { name: "help@example.com" })).toHaveAttribute("href", "mailto:help@example.com");
  expect(screen.getByRole("link", { name: "Contact support" })).toHaveAttribute("href", "https://example.com/help");
  expect(screen.getByRole("main").style.getPropertyValue("--color-secondary")).toBe("255 255 255");
  expect(document.documentElement.style.getPropertyValue("--color-secondary")).toBe("");
});
