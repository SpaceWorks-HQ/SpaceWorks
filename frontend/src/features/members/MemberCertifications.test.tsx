import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { memberRequest } from "../../lib/api";
import { MemberCertifications } from "./MemberCertifications";

vi.mock("../../lib/api", () => ({ memberRequest: vi.fn() }));

function show() {
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><MemberCertifications makerspaceId={3} /></QueryClientProvider>);
}

describe("own certification history", () => {
  it("renders expiry and renewal guidance using server validity", async () => {
    vi.mocked(memberRequest).mockResolvedValue({ count: 1, next: null, previous: null, results: [{ id: 1, name: "Laser safety", machine_type_name: "Laser", type_active: true, is_live: false, granted_at: "2020-01-01T00:00:00Z", expires_at: "2021-01-01T00:00:00Z", revoked_at: null }] });
    show();
    expect(await screen.findByText("Laser safety")).toBeVisible();
    expect(screen.getByText("Laser · Expired")).toBeVisible();
    expect(screen.getByText("Ask staff to reassess and renew your training.")).toBeVisible();
    expect(memberRequest).toHaveBeenCalledWith("/member/makerspaces/3/certifications?page=1");
  });
  it("keeps an unavailable history distinct from no records", async () => {
    vi.mocked(memberRequest).mockRejectedValue(new Error("History unavailable"));
    show();
    expect(await screen.findByRole("alert")).toHaveTextContent("History unavailable");
    expect(screen.queryByText("No training records yet. Ask staff about machine induction.")).toBeNull();
  });
});
