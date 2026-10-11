import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { PaymentDocuments } from "./PaymentDocuments";

const api = vi.hoisted(() => ({ staffRequest: vi.fn(), memberRequest: vi.fn(), staffRequestBlob: vi.fn(), memberRequestBlob: vi.fn() }));
vi.mock("../../lib/api", () => api);
const receipt = { id: 21, payment: 11, number: "SW-000001", kind: "receipt", amount: "10.00", currency: "usd", issued_at: "2026-10-11T00:00:00Z", money_at: "2026-10-11T00:00:00Z" };

function mount(audience: "staff" | "member") {
  return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })}>
    <PaymentDocuments makerspaceId={7} audience={audience} />
  </QueryClientProvider>);
}

beforeEach(() => {
  vi.resetAllMocks();
  for (const request of [api.staffRequest, api.memberRequest]) request.mockImplementation(async (path: string) => path.includes("download-url")
    ? { url: "/api/v1/payment-documents/21/download?token=short-lived", expires_in: 300 }
    : { count: 1, next: null, previous: null, results: [receipt] });
  api.staffRequestBlob.mockResolvedValue(new Blob(["pdf"]));
  api.memberRequestBlob.mockResolvedValue(new Blob(["pdf"]));
  URL.createObjectURL = vi.fn(() => "blob:receipt");
  URL.revokeObjectURL = vi.fn();
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
});

describe("Payment documents", () => {
  it.each(["staff", "member"] as const)("requests %s grants and fetches PDF with authentication", async audience => {
    mount(audience);
    fireEvent.click(screen.getByRole("button", { name: "Show documents" }));
    expect(await screen.findByText("Receipt SW-000001")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Download PDF" }));
    const request = audience === "member" ? api.memberRequest : api.staffRequest;
    const blob = audience === "member" ? api.memberRequestBlob : api.staffRequestBlob;
    await waitFor(() => expect(request).toHaveBeenCalledWith(`${audience === "member" ? "/member/makerspaces" : "/admin/makerspace"}/7/payment-documents/21/download-url`));
    await waitFor(() => expect(blob).toHaveBeenCalledWith("/payment-documents/21/download?token=short-lived"));
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:receipt");
  });

  it("shows grant failures without attempting a binary download", async () => {
    api.staffRequest.mockImplementation(async (path: string) => {
      if (path.includes("download-url")) throw new Error("Receipt access was revoked");
      return { count: 1, next: null, previous: null, results: [receipt] };
    });
    mount("staff");
    fireEvent.click(screen.getByRole("button", { name: "Show documents" }));
    fireEvent.click(await screen.findByRole("button", { name: "Download PDF" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Receipt access was revoked");
    expect(api.staffRequestBlob).not.toHaveBeenCalled();
  });
});
