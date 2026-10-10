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

afterEach(() => { vi.restoreAllMocks(); document.documentElement.className = ""; });

it.each(["light", "dark", "invalid"])("renders member support contacts and scoped tokens for %s palettes", async (mode) => {
  document.documentElement.classList.toggle("dark", mode === "dark");
  const primary = mode === "dark" ? "#004400" : mode === "invalid" ? "#777" : "#fff";
  bootstrapTenant.mockResolvedValue({
    makerspace: { id: 7, slug: "brand-space", name: "Brand Space", membership_policy: "invite_only" },
    modules: [], theme: { primary_color: primary, accent_color: "#000" },
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
  if (mode === "dark") Object.assign(tokens, { bg: "22 22 28", surface: "38 40 51", panel: "29 30 38" });
  vi.spyOn(window, "getComputedStyle").mockReturnValue({
    getPropertyValue: (name: string) => tokens[name.replace("--color-", "")] ?? "",
  } as CSSStyleDeclaration);
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <MemoryRouter><MemberArea /></MemoryRouter>
  </QueryClientProvider>);
  expect(await screen.findByRole("link", { name: "help@example.com" })).toHaveAttribute("href", "mailto:help@example.com");
  expect(screen.getByRole("link", { name: "Contact support" })).toHaveAttribute("href", "https://example.com/help");
  const style = screen.getByRole("main").style;
  if (mode === "invalid") {
    expect(style.length).toBe(0);
  } else {
    expect(style.getPropertyValue("--color-secondary")).toBe(mode === "dark" ? "0 68 0" : "255 255 255");
    expect(style.getPropertyValue("--color-on-secondary")).toBe(mode === "dark" ? "255 255 255" : "0 0 0");
    expect(style.getPropertyValue("--color-secondary-hover")).toBe(mode === "dark" ? "0 63 0" : "255 255 255");
    expect(style.getPropertyValue("--color-secondary-active")).toBe(mode === "dark" ? "0 57 0" : "255 255 255");
    expect(style.getPropertyValue("--color-secondary-boundary")).toBe(style.getPropertyValue("--color-secondary-ink"));
  }
  expect(document.documentElement.style.getPropertyValue("--color-secondary")).toBe("");
});
